from __future__ import annotations
from dotenv import load_dotenv
import os
import asyncpg
import logging
from datetime import datetime
from livekit import agents
from livekit.agents import AgentSession, Agent, RoomInputOptions, JobContext
from livekit.agents.llm import function_tool
from livekit.plugins import (
    openai,
    noise_cancellation
)
from livekit import api
from livekit.protocol.sip import TransferSIPParticipantRequest
from dataclasses import dataclass
from typing import Optional, Dict, Any


load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
pool = None

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def verify_user_pin(pin: str) -> Dict[str, Any]:
    """Verify user PIN and return user details if found."""
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT * FROM user_data WHERE pin = $1",
            pin
        )
        return dict(user) if user else None

async def update_account_status(pin: str, status: str):
    """Update user account status with automatic timestamp update."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE user_data SET account_status = $1 WHERE pin = $2",
            status, pin
        )

async def update_password(pin: str, new_password: str):
    """Update user password with automatic timestamp update."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE user_data SET password = $1 WHERE pin = $2",
            new_password, pin
        )

async def update_issue_type(pin: str, issue_type: str):
    """Update user issue type with automatic timestamp update."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE user_data SET issue_type = $1 WHERE pin = $2",
            issue_type, pin
        )

async def log_user_interaction(pin: str, location: str):
    """Update user location with automatic timestamp update."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE user_data SET location = $1 WHERE pin = $2",
            location, pin
        )

@dataclass
class ITSupportData:
    """Store user data and state for IT support call agent."""
    pin: str = None
    name: str = None
    phone_number: str = None
    account_status: str = None
    password: str = None
    postal_code: str = None
    date_of_birth: str = None
    sin_last_three: str = None
    location: str = None
    issue_type: str = None
    ctx: JobContext = None

class ITSupportAgent(Agent):
    def __init__(self, user_data: ITSupportData) -> None:
        instructions = """You are an IT Support Agent for CN Service Desk. Your role is to help employees with technical issues.

        GREETING: Always start with: "Thank you for calling the CN Service Desk. My name is Rachel. May I have your PIN number please?"

        VERIFICATION PROCESS (MUST BE COMPLETED IN ORDER):
        1. PIN number verification from database
        2. Confirm user's name and phone number from database
        3. Ask for user's current location (home/office)
        4. For account unlock/password reset requests, verify security questions:
           - Postal code
           - Date of birth (dd/mm/yyyy format)
           - Last three digits of social insurance number

        ISSUE CLASSIFICATION:
        You must classify all issues into one of these categories:
        - "account_locked": User cannot log in due to locked account
        - "password_reset": User needs password reset or forgot password
        - "others": All other technical issues (network, software, hardware, etc.)

        PROCESS:
        1. Verify PIN and retrieve user details
        2. Confirm user identity
        3. Ask about current location and log it
        4. Understand and classify the technical issue
        5. Update issue type in database
        6. For account issues:
           - If locked: Offer unlock or password reset
           - Verify security questions
           - Update account status/password
        7. For "others" issues: Transfer to human specialist
        8. Confirm resolution with user

        IMPORTANT RULES:
        - Always maintain professional, helpful tone
        - Complete identity verification before any action
        - For account operations, must verify all 3 security questions
        - Always classify and log the issue type
        - Transfer to human agent for non-account issues or if requested
        - Test solutions with user before closing
        - Update database when any changes are made

        Use the provided functions to collect information and perform actions."""

        super().__init__(instructions=instructions)
        self.user_data = user_data

    @function_tool()
    async def verify_pin_and_get_details(self, pin_number: str):
        """Verify PIN and retrieve user details from database."""
        user_details = await verify_user_pin(pin_number)
        if not user_details:
            return "I'm sorry, but I couldn't find any account with that PIN number. Could you please verify and provide the correct PIN?"
        
        self.user_data.pin = pin_number
        self.user_data.name = user_details['name']
        self.user_data.phone_number = user_details['phone_number']
        self.user_data.account_status = user_details['account_status']
        self.user_data.password = user_details['password']
        self.user_data.postal_code = user_details['postal_code']
        self.user_data.date_of_birth = user_details['date_of_birth']
        self.user_data.sin_last_three = user_details['sin_last_three']
        
        return f"I found your account. Could you please confirm if your name is {user_details['name']} and your phone number is {user_details['phone_number']}?"

    @function_tool()
    async def set_location_and_ask_issue(self, location: str):
        """Set the user's current location and ask about their issue."""
        self.user_data.location = location
        
        # Log the location in database
        if self.user_data.pin:
            await log_user_interaction(self.user_data.pin, location)
            logger.info(f"Updated location for user {self.user_data.name}: {location}")
        
        return f"Thank you for confirming your location as {location}. What technical issue are you experiencing today? Are you having trouble logging into your account, do you need a password reset, or is it a different technical problem?"

    @function_tool()
    async def classify_and_log_issue(self, issue_description: str, issue_type: str):
        """Classify the user's issue and log it in the database."""
        valid_types = ["account_locked", "password_reset", "others"]
        
        if issue_type not in valid_types:
            return f"Invalid issue type. Please classify as one of: {', '.join(valid_types)}"
        
        self.user_data.issue_type = issue_type
        
        # Update issue type in database
        if self.user_data.pin:
            await update