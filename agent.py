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
            "SELECT * FROM user_accounts WHERE pin = $1",
            pin
        )
        return dict(user) if user else None

async def update_account_status(pin: str, status: str):
    """Update user account status with timestamp."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE user_accounts SET account_status = $1, updated_at = CURRENT_TIMESTAMP WHERE pin = $2",
            status, pin
        )

async def update_password(pin: str, new_password: str):
    """Update user password with timestamp."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE user_accounts SET password = $1, updated_at = CURRENT_TIMESTAMP WHERE pin = $2",
            new_password, pin
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

        CONVERSATION FLOW:
        1. Ask for PIN number
        2. If PIN exists in database:
           - Confirm user's name and phone number
           - Ask for location (home/office)
           - Ask about the issue
        3. Based on the issue:
           - If account is locked:
             * Ask security questions (postal code, DOB, SIN last 3)
             * If verified, unlock account
           - If password reset requested:
             * Ask security questions
             * If verified, ask for new password and update
             * If account was locked, set to active
           - If other issues:
             * Transfer to human agent
        4. Provide call summary

        IMPORTANT RULES:
        - Always maintain professional, helpful tone
        - Complete identity verification before any action
        - For account operations, must verify all 3 security questions
        - Transfer to human agent for non-account issues
        - Test solutions with user before closing

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
    async def set_location(self, location: str):
        """Set the user's current location."""
        if location.lower() not in ['home', 'office']:
            return "Please specify if you're at home or office."
        
        self.user_data.location = location.lower()
        return f"Thank you for confirming your location. What technical issue are you experiencing today?"

    @function_tool()
    async def set_issue_type(self, issue: str):
        """Set the type of issue the user is experiencing."""
        issue = issue.lower()
        if 'lock' in issue or 'locked' in issue:
            self.user_data.issue_type = 'account_locked'
            if self.user_data.account_status == 'locked':
                return "I understand your account is locked. To help you unlock it, I'll need to verify some security information. Could you please provide your postal code?"
            else:
                return "I see that your account is actually active. Is there something else I can help you with?"
        elif 'password' in issue or 'reset' in issue:
            self.user_data.issue_type = 'password_reset'
            return "I'll help you reset your password. First, I need to verify your identity. Could you please provide your postal code?"
        else:
            self.user_data.issue_type = 'other'
            return "I understand you're experiencing a different issue. Let me transfer you to one of our technical specialists who can help you better."

    @function_tool()
    async def verify_security_questions(self, postal_code: str, date_of_birth: str, sin_last_three: str):
        """Verify security questions against database records."""
        if not self.user_data.pin:
            return "Please provide your PIN number first."
        
        if (postal_code == self.user_data.postal_code and
            date_of_birth == self.user_data.date_of_birth and
            sin_last_three == self.user_data.sin_last_three):
            return "Security verification successful. All information matches our records."
        else:
            return "I'm sorry, but the security information provided doesn't match our records. Please try again."

    @function_tool()
    async def unlock_account(self):
        """Unlock the user's account after security verification."""
        if self.user_data.account_status != 'locked':
            return "Your account is not locked. Is there something else I can help you with?"
            
        await update_account_status(self.user_data.pin, 'active')
        logger.info(f"Unlocked account for user: {self.user_data.name}")
        return "Your account has been successfully unlocked. You can now log in with your regular password."

    @function_tool()
    async def reset_password(self, new_password: str):
        """Reset the user's password after verification."""
        if not new_password:
            return "Please provide a new password."
            
        await update_password(self.user_data.pin, new_password)
        if self.user_data.account_status == 'locked':
            await update_account_status(self.user_data.pin, 'active')
        logger.info(f"Reset password for user: {self.user_data.name}")
        return "Your password has been successfully reset. You can now log in with your new password."

    @function_tool()
    async def transfer_to_specialist(self) -> str:
        """Transfer the call to a human agent."""
        try:
            human_agent_phone = os.getenv("HUMAN_AGENT_PHONE")
            if not human_agent_phone:
                logger.error("HUMAN_AGENT_PHONE environment variable not set")
                return "I'm unable to transfer your call right now. Please call our specialist line directly at extension 5555 for advanced technical support."
            
            transfer_to = "tel:" + human_agent_phone
            
            if not self.user_data.ctx or not self.user_data.ctx.room:
                logger.error("No room context available for transfer")
                return "I'll need to escalate this to a specialist. Please call our specialist line directly at extension 5555."
            
            room_name = self.user_data.ctx.room.name
            participant_identity = None
            
            participants = list(self.user_data.ctx.room.remote_participants.values())
            for participant in participants:
                if (participant.identity and 
                    (participant.identity.startswith("+") or 
                     participant.identity.startswith("tel:"))):
                    participant_identity = participant.identity
                    break
            
            if not participant_identity and participants:
                participant_identity = participants[0].identity
            
            if not participant_identity:
                logger.error("Could not identify participant for transfer")
                return "I'll need to escalate this to a specialist. Please call our specialist line directly at extension 5555."
            
            async with api.LiveKitAPI(
                url=os.getenv("LIVEKIT_URL"),
                api_key=os.getenv("LIVEKIT_API_KEY"),
                api_secret=os.getenv("LIVEKIT_API_SECRET"),
            ) as livekit_api:
                transfer_request = TransferSIPParticipantRequest(
                    participant_identity=participant_identity,
                    room_name=room_name,
                    transfer_to=transfer_to,
                    play_dialtone=False
                )
                
                await livekit_api.sip.transfer_sip_participant(transfer_request)
                return "I'm transferring you to one of our technical specialists who can help you further. Please hold while I connect you."
            
        except Exception as e:
            logger.error(f"Failed to transfer call: {str(e)}", exc_info=True)
            return "I'm unable to transfer your call right now. Please call our specialist line directly at extension 5555 for advanced technical support."

    @function_tool()
    async def get_call_summary(self):
        """Generate a summary of the support call."""
        summary = f"""
        Call Summary:
        - User: {self.user_data.name or 'Unknown'}
        - Issue: {self.user_data.issue_type or 'General Support'}
        - Location: {self.user_data.location or 'Not specified'}
        - Account Status: {self.user_data.account_status or 'Unknown'}
        - Action Taken: {self.user_data.issue_type == 'other' and 'Transferred to specialist' or 'Issue resolved'}
        """
        return summary.strip()

async def entrypoint(ctx: JobContext):
    global pool
    if pool is None:
        pool = await asyncpg.create_pool(DATABASE_URL)

    session = AgentSession(
        llm=openai.realtime.RealtimeModel(
            voice="alloy"
        )
    )

    await session.start(
        room=ctx.room,
        agent=ITSupportAgent(ITSupportData(ctx=ctx)),
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC()
        )
    )

    await ctx.connect()

    session.generate_reply(user_input="""Begin the conversation with this exact greeting: 
    'Thank you for calling the CN Service Desk. My name is Rachel. May I have your PIN number please?'""")

if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(
        entrypoint_fnc=entrypoint,
        agent_name="cn_call_agent"
    ))
