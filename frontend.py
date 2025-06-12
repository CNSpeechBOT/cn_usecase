import streamlit as st
import psycopg2
import pandas as pd
from datetime import datetime
import hashlib

# Database connection URL
DATABASE_URL = "postgresql://cnspeechbot_user:9rFkovPCCwTM3fvKyZELbDyQZRCDmjVJ@dpg-d1572pbe5dus739b360g-a.virginia-postgres.render.com/cnspeechbot"

# Configure Streamlit page
st.set_page_config(
    page_title="User Data Management",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Valid issue types
VALID_ISSUE_TYPES = ["account_locked", "password_reset", "others"]

def get_connection():
    """Create database connection"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        st.error(f"Database connection failed: {e}")
        return None

@st.cache_data(ttl=60)  # Cache for 60 seconds
def fetch_data():
    """Fetch all data from the user_data table"""
    try:
        conn = get_connection()
        if conn:
            query = """
            SELECT pin, name, phone_number, account_status, password, 
                   postal_code, date_of_birth, sin_last_three, location, 
                   issue_type, created_at, updated_at
            FROM user_data 
            ORDER BY created_at DESC
            """
            df = pd.read_sql_query(query, conn)
            conn.close()
            return df
        else:
            return pd.DataFrame()
    except Exception as e:
        st.error(f"Error fetching data: {e}")
        return pd.DataFrame()

def insert_data(data):
    """Insert new row into the database"""
    try:
        conn = get_connection()
        if conn:
            cursor = conn.cursor()
            
            insert_query = """
            INSERT INTO user_data (pin, name, phone_number, account_status, password, 
                                 postal_code, date_of_birth, sin_last_three, location, 
                                 issue_type)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            cursor.execute(insert_query, data)
            conn.commit()
            cursor.close()
            conn.close()
            return True
    except Exception as e:
        st.error(f"Error inserting data: {e}")
        return False

def update_record(pin, field, value):
    """Update a specific field in a record using PIN as identifier"""
    try:
        conn = get_connection()
        if conn:
            cursor = conn.cursor()
            
            # Validate issue_type if that's what we're updating
            if field == 'issue_type' and value not in VALID_ISSUE_TYPES:
                st.error(f"Invalid issue type. Must be one of: {', '.join(VALID_ISSUE_TYPES)}")
                return False
            
            # Use parameterized query with PIN as identifier
            query = f"UPDATE user_data SET {field} = %s WHERE pin = %s"
            cursor.execute(query, (value, pin))
            conn.commit()
            cursor.close()
            conn.close()
            return True
    except Exception as e:
        st.error(f"Error updating record: {e}")
        return False

def delete_record(pin):
    """Delete a record by PIN"""
    try:
        conn = get_connection()
        if conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM user_data WHERE pin = %s", (pin,))
            conn.commit()
            cursor.close()
            conn.close()
            return True
    except Exception as e:
        st.error(f"Error deleting record: {e}")
        return False

def hash_password(password):
    """Hash password for security"""
    return hashlib.sha256(password.encode()).hexdigest()

def main():
    st.title("📊 User Data Management System")
    st.markdown("---")
    
    # Sidebar for navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.radio("Select Page", ["View Data", "Add New Record", "Update Records", "Statistics"])
    
    if page == "View Data":
        st.header("📋 Current Database Records")
        
        # Refresh button
        if st.button("🔄 Refresh Data"):
            fetch_data.clear()
        
        # Fetch and display data
        df = fetch_data()
        
        if not df.empty:
            st.subheader(f"Total Records: {len(df)}")
            
            # Search functionality
            search_term = st.text_input("🔍 Search records (by name, phone, or location):")
            if search_term:
                mask = (
                    df['name'].str.contains(search_term, case=False, na=False) |
                    df['phone_number'].str.contains(search_term, case=False, na=False) |
                    df['location'].str.contains(search_term, case=False, na=False)
                )
                df = df[mask]
                st.info(f"Found {len(df)} matching records")
            
            # Display table with better formatting
            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "pin": "PIN",
                    "name": "Name",
                    "phone_number": "Phone",
                    "account_status": "Status",
                    "password": st.column_config.TextColumn("Password", help="Hashed passwords"),
                    "postal_code": "Postal Code",
                    "date_of_birth": "DOB",
                    "sin_last_three": "SIN (Last 3)",
                    "location": "Location",
                    "issue_type": "Issue Type",
                    "created_at": st.column_config.DatetimeColumn("Created At"),
                    "updated_at": st.column_config.DatetimeColumn("Updated At")
                }
            )
            
            # Delete functionality
            st.subheader("🗑️ Delete Record")
            col1, col2 = st.columns([3, 1])
            with col1:
                record_to_delete = st.selectbox(
                    "Select record to delete:",
                    options=df['pin'].tolist(),
                    format_func=lambda x: f"PIN: {x} - {df[df['pin']==x]['name'].iloc[0] if not df[df['pin']==x].empty else 'Unknown'}"
                )
            with col2:
                if st.button("🗑️ Delete", type="secondary"):
                    if st.session_state.get('confirm_delete', False):
                        if delete_record(record_to_delete):
                            st.success("Record deleted successfully!")
                            st.cache_data.clear()
                            st.rerun()
                        st.session_state.confirm_delete = False
                    else:
                        st.session_state.confirm_delete = True
                        st.warning("Click delete again to confirm")
        else:
            st.info("No records found in the database.")
    
    elif page == "Add New Record":
        st.header("➕ Add New User Record")
        
        with st.form("add_record_form"):
            col1, col2 = st.columns(2)
            
            with col1:
                pin = st.text_input("PIN", help="User PIN number")
                name = st.text_input("Full Name", help="User's full name")
                phone_number = st.text_input("Phone Number", help="Format: +1-555-0123")
                account_status = st.selectbox(
                    "Account Status",
                    ["active", "locked", "suspended", "pending"],
                    help="Current account status"
                )
                password = st.text_input("Password", type="password", help="Will be hashed before storing")
                postal_code = st.text_input("Postal Code", help="User's postal/zip code")
            
            with col2:
                date_of_birth = st.date_input("Date of Birth", help="User's birth date")
                sin_last_three = st.text_input("SIN (Last 3 digits)", max_chars=3, help="Last 3 digits of SIN")
                location = st.text_input("Location", help="Current location (home/office)")
                issue_type = st.selectbox(
                    "Issue Type",
                    VALID_ISSUE_TYPES,
                    help="Type of issue - classified by agent"
                )
            
            submitted = st.form_submit_button("➕ Add Record", type="primary")
            
            if submitted:
                # Validate required fields
                if not pin or not name or not phone_number:
                    st.error("PIN, Name and Phone Number are required fields!")
                elif sin_last_three and len(sin_last_three) != 3:
                    st.error("SIN last three digits must be exactly 3 characters!")
                elif issue_type not in VALID_ISSUE_TYPES:
                    st.error(f"Invalid issue type. Must be one of: {', '.join(VALID_ISSUE_TYPES)}")
                else:
                    # Prepare data
                    hashed_password = hash_password(password) if password else None
                    dob_str = date_of_birth.strftime("%d/%m/%Y") if date_of_birth else None
                    
                    data = (
                        pin,
                        name,
                        phone_number,
                        account_status,
                        hashed_password,
                        postal_code,
                        dob_str,
                        sin_last_three,
                        location,
                        issue_type
                    )
                    
                    if insert_data(data):
                        st.success("✅ Record added successfully!")
                        fetch_data.clear()
                        st.balloons()
                    else:
                        st.error("❌ Failed to add record. Please try again.")
    
    elif page == "Update Records":
        st.header("✏️ Update Existing Records")
        
        df = fetch_data()
        
        if not df.empty:
            # Select record to update
            record_to_update = st.selectbox(
                "Select record to update:",
                options=df['pin'].tolist(),
                format_func=lambda x: f"PIN: {x} - {df[df['pin']==x]['name'].iloc[0] if not df[df['pin']==x].empty else 'Unknown'}"
            )
            
            if record_to_update:
                selected_record = df[df['pin'] == record_to_update].iloc[0]
                
                st.subheader(f"Updating Record for: {selected_record['name']}")
                
                col1, col2 = st.columns(2)
                
                with col1:
                    st.write("**Current Account Status:**", selected_record['account_status'])
                    new_status = st.selectbox(
                        "Update Account Status:",
                        ["active", "locked", "suspended", "pending"],
                        index=["active", "locked", "suspended", "pending"].index(selected_record['account_status']) if selected_record['account_status'] in ["active", "locked", "suspended", "pending"] else 0
                    )
                    
                    if st.button("Update Status"):
                        if update_record(record_to_update, 'account_status', new_status):
                            st.success("Account status updated successfully!")
                            fetch_data.clear()
                            st.rerun()
                
                with col2:
                    st.write("**Current Issue Type:**", selected_record['issue_type'])
                    new_issue_type = st.selectbox(
                        "Update Issue Type:",
                        VALID_ISSUE_TYPES,
                        index=VALID_ISSUE_TYPES.index(selected_record['issue_type']) if selected_record['issue_type'] in VALID_ISSUE_TYPES else 0
                    )
                    
                    if st.button("Update Issue Type"):
                        if update_record(record_to_update, 'issue_type', new_issue_type):
                            st.success("Issue type updated successfully!")
                            fetch_data.clear()
                            st.rerun()
                
                # Password reset section
                st.subheader("🔐 Password Reset")
                new_password = st.text_input("New Password", type="password")
                if st.button("Reset Password"):
                    if new_password:
                        hashed_password = hash_password(new_password)
                        if update_record(record_to_update, 'password', hashed_password):
                            st.success("Password updated successfully!")
                            fetch_data.clear()
                            st.rerun()
                    else:
                        st.error("Please enter a new password")
                
                # Show last updated
                st.info(f"Last updated: {selected_record['updated_at']}")
        else:
            st.info("No records available to update.")
    
    elif page == "Statistics":
        st.header("📈 Database Statistics")
        
        df = fetch_data()
        
        if not df.empty:
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.metric("Total Records", len(df))
            
            with col2:
                active_count = len(df[df['account_status'] == 'active'])
                st.metric("Active Accounts", active_count)
            
            with col3:
                locked_count = len(df[df['account_status'] == 'locked'])
                st.metric("Locked Accounts", locked_count)
            
            with col4:
                recent_count = len(df[pd.to_datetime(df['updated_at']) > pd.Timestamp.now() - pd.Timedelta(days=7)])
                st.metric("Updated This Week", recent_count)
            
            # Charts
            st.subheader("📊 Account Status Distribution")
            status_counts = df['account_status'].value_counts()
            st.bar_chart(status_counts)
            
            st.subheader("📊 Issue Type Distribution")
            issue_counts = df['issue_type'].value_counts()
            st.bar_chart(issue_counts)
            
            # Recent activity
            st.subheader("🕒 Recent Activity")
            recent_df = df.head(10)[['name', 'account_status', 'issue_type', 'updated_at']]
            st.dataframe(recent_df, use_container_width=True, hide_index=True)
            
            # Updated vs Created comparison
            st.subheader("📅 Record Timestamps")
            timestamp_df = df[['name', 'created_at', 'updated_at']].copy()
            timestamp_df['created_at'] = pd.to_datetime(timestamp_df['created_at'])
            timestamp_df['updated_at'] = pd.to_datetime(timestamp_df['updated_at'])
            timestamp_df['was_updated'] = timestamp_df['updated_at'] > timestamp_df['created_at']
            
            updated_count = len(timestamp_df[timestamp_df['was_updated']])
            st.metric("Records Modified After Creation", updated_count)
            
        else:
            st.info("No data available for statistics.")

if __name__ == "__main__":
    main()