import psycopg2
from psycopg2 import sql
import os

# Database connection URL
DATABASE_URL = "postgresql://cnspeechbot_user:9rFkovPCCwTM3fvKyZELbDyQZRCDmjVJ@dpg-d1572pbe5dus739b360g-a.virginia-postgres.render.com/cnspeechbot"

def create_table():
    """
    Create a table with the specified schema in the PostgreSQL database.
    """
    
    # SQL query to create the table without id column
    create_table_query = """
    CREATE TABLE IF NOT EXISTS user_data (
        pin VARCHAR(255),
        name VARCHAR(255),
        phone_number VARCHAR(255),
        account_status VARCHAR(255),
        password VARCHAR(255),
        postal_code VARCHAR(255),
        date_of_birth VARCHAR(255),
        sin_last_three VARCHAR(255),
        location VARCHAR(255),
        issue_type VARCHAR(255) CHECK (issue_type IN ('account_locked', 'password_reset', 'others')),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    
    # Create trigger function to automatically update updated_at timestamp
    trigger_function_query = """
    CREATE OR REPLACE FUNCTION update_updated_at_column()
    RETURNS TRIGGER AS $$
    BEGIN
        NEW.updated_at = CURRENT_TIMESTAMP;
        RETURN NEW;
    END;
    $$ language 'plpgsql';
    """
    
    # Create trigger to call the function on any update
    trigger_query = """
    DROP TRIGGER IF EXISTS update_user_data_updated_at ON user_data;
    CREATE TRIGGER update_user_data_updated_at
        BEFORE UPDATE ON user_data
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column();
    """
    
    try:
        # Connect to the database
        print("Connecting to the database...")
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        # Execute the create table query
        print("Creating table...")
        cursor.execute(create_table_query)
        
        # Create the trigger function
        print("Creating trigger function...")
        cursor.execute(trigger_function_query)
        
        # Create the trigger
        print("Creating trigger...")
        cursor.execute(trigger_query)
        
        # Commit the changes
        conn.commit()
        print("Table 'user_data' created successfully with auto-updating timestamp!")
        
        # Verify table creation by checking if it exists
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_name = 'user_data';
        """)
        
        result = cursor.fetchone()
        if result:
            print(f"✓ Table '{result[0]}' exists in the database")
            
            # Verify trigger exists
            cursor.execute("""
                SELECT trigger_name 
                FROM information_schema.triggers 
                WHERE event_object_table = 'user_data' AND trigger_name = 'update_user_data_updated_at';
            """)
            
            trigger_result = cursor.fetchone()
            if trigger_result:
                print(f"✓ Trigger '{trigger_result[0]}' created successfully")
            else:
                print("⚠ Trigger creation verification failed")
        else:
            print("✗ Table creation verification failed")
            
    except psycopg2.Error as e:
        print(f"Database error: {e}")
        
    except Exception as e:
        print(f"Error: {e}")
        
    finally:
        # Close the connection
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()
        print("Database connection closed.")

def migrate_existing_data():
    """
    Migrate existing data by removing ctx and id columns and updating issue_type values.
    """
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        # Check if ctx column exists and drop it
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'user_data' AND column_name = 'ctx';
        """)
        
        if cursor.fetchone():
            print("Dropping ctx column...")
            cursor.execute("ALTER TABLE user_data DROP COLUMN IF EXISTS ctx;")
        
        # Check if id column exists and drop it
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'user_data' AND column_name = 'id';
        """)
        
        if cursor.fetchone():
            print("Dropping id column...")
            cursor.execute("ALTER TABLE user_data DROP COLUMN IF EXISTS id;")
        
        # Update existing issue_type values to match new constraints
        print("Updating existing issue_type values...")
        cursor.execute("""
            UPDATE user_data 
            SET issue_type = CASE 
                WHEN issue_type LIKE '%account%' OR issue_type LIKE '%lock%' THEN 'account_locked'
                WHEN issue_type LIKE '%password%' OR issue_type LIKE '%reset%' THEN 'password_reset'
                ELSE 'others'
            END
            WHERE issue_type NOT IN ('account_locked', 'password_reset', 'others');
        """)
        
        # Add constraint if it doesn't exist
        cursor.execute("""
            ALTER TABLE user_data 
            DROP CONSTRAINT IF EXISTS user_data_issue_type_check;
        """)
        
        cursor.execute("""
            ALTER TABLE user_data 
            ADD CONSTRAINT user_data_issue_type_check 
            CHECK (issue_type IN ('account_locked', 'password_reset', 'others'));
        """)
        
        conn.commit()
        print("Data migration completed successfully!")
        
    except psycopg2.Error as e:
        print(f"Migration error: {e}")
        conn.rollback()
        
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()

def insert_sample_data():
    """
    Insert sample data into the table with updated schema.
    """
    insert_query = """
    INSERT INTO user_data (pin, name, phone_number, account_status, password, postal_code, date_of_birth, sin_last_three, location, issue_type)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
    """
    
    sample_data = (
        "1234",
        "John Doe",
        "+1-555-0123",
        "locked",
        "hashed_password_here",
        "12345",
        "01/01/1990",
        "123",
        "office",
        "account_locked"
    )
    
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        cursor.execute(insert_query, sample_data)
        conn.commit()
        print("Sample data inserted successfully!")
        
    except psycopg2.Error as e:
        print(f"Error inserting sample data: {e}")
        
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()

def drop_columns():
    """
    Drop issue_type and location columns from the user_data table.
    """
    try:
        # Connect to the database
        print("Connecting to the database...")
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        # Drop the columns
        print("Dropping columns...")
        cursor.execute("ALTER TABLE user_data DROP COLUMN IF EXISTS issue_type;")
        cursor.execute("ALTER TABLE user_data DROP COLUMN IF EXISTS location;")
        
        # Commit the changes
        conn.commit()
        print("Columns 'issue_type' and 'location' dropped successfully!")
        
    except psycopg2.Error as e:
        print(f"Database error: {e}")
        
    except Exception as e:
        print(f"Error: {e}")
        
    finally:
        # Close the connection
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()
        print("Database connection closed.")

if __name__ == "__main__":
    # Create the table with updated schema
    create_table()
    
    # Migrate existing data (run this once if you have existing data)
    migrate_existing_data()
    
    # Uncomment the line below if you want to insert sample data
    # insert_sample_data()
    
    # Drop issue_type and location columns
    drop_columns()
