import pandas as pd
import re  # Import the regular expression module
import os

def read_dates_from_file(filepath):
    """Reads dates from a text file.

    Args:
        filepath (str): The path to the text file.

    Returns:
        list: A list of dates read from the file, or an empty list on error.
    """
    try:
        with open(filepath, 'r') as f:
            content = f.read()
            # Extract the date string using regex
            match = re.search(r'const expiryDatesList = "(.*)";', content)
            if match:
                date_string = match.group(1)
                dates = date_string.split(',')
                return [d.strip() for d in dates if d.strip()] # Remove empty strings
            else:
                print(f"Warning: Could not find date list in {filepath}.  Returning empty list.")
                return []
    except FileNotFoundError:
        print(f"Warning: File not found at {filepath}. Returning empty list.")
        return []
    except Exception as e:
        print(f"Error reading file {filepath}: {e}. Returning empty list.")
        return []

def read_dates_from_csv(filepath, date_column_name='expirydate', output_date_format='%Y-%m-%d'):
    """Reads dates from a CSV file and returns them in the specified format.

    Args:
        filepath (str): The path to the CSV file.
        date_column_name (str, optional): The name of the column containing dates.
                                         Defaults to 'ExpiryDate' based on your image.
        output_date_format (str, optional): The desired output string format for the dates.
                                            Defaults to '%Y-%m-%d'.

    Returns:
        list: A list of unique dates in the specified output format,
              or an empty list on error.
    """
    try:
        df = pd.read_csv(filepath)
        #print(df)

        # Check if the date column exists
        if date_column_name not in df.columns:
            print(f"Error: Column '{date_column_name}' not found in CSV file {filepath}")
            return []

        # Drop rows where the date column might be NaN to avoid errors during conversion
        # and ensure all values are strings before attempting date conversion.
        date_series = df[date_column_name].dropna().astype(str)
        #print(date_series)
        # Convert the date strings to datetime objects
        # The format '%d-%b-%y' matches '26-Jun-25'
        # errors='coerce' will turn unparseable dates into NaT (Not a Time),
        # which we can then drop.
        datetime_series = pd.to_datetime(date_series, format='%d-%b-%Y', errors='coerce')       
        #print(datetime_series) 
        # Drop any NaT values that resulted from parsing errors
        valid_datetime_series = datetime_series.dropna()

        # Format the datetime objects to the desired string format
        formatted_dates_series = valid_datetime_series.dt.strftime(output_date_format)

        # Get unique dates and convert to a list
        unique_formatted_dates = formatted_dates_series.unique().tolist()

        return unique_formatted_dates
    except FileNotFoundError:
        print(f"Error: File not found at {filepath}")
        return []
    except KeyError: # Should be caught by the explicit check above, but good as a fallback
        print(f"Error: Column '{date_column_name}' not found in CSV file {filepath}")
        return []
    except Exception as e:
        print(f"Error reading or processing CSV file {filepath}: {e}")
        return []

def format_date(date_str):
    """Formats a date string into YYYY-MM-DD format, handling multiple date formats.

    Args:
        date_str (str): The date string to format.

    Returns:
        str: The formatted date string, or None if formatting fails.
    """
    # Define a list of possible date formats to try
    formats_to_try = [
        '%d-%m-%Y',  # e.g., 01-01-2023
        '%d/%m/%Y',  # e.g., 01/01/2023
        '%Y-%m-%d',  # e.g., 2023-01-01
        '%Y/%m/%d',  # e.g., 2023/01/01
        '%m/%d/%Y',  # e.g., 01/01/2023 (US format)
        '%m-%d-%Y',
        '%d-%m-%y', # 01-01-23
        '%d/%m/%y',
        '%Y-%m-%y',
        '%Y/%m/%y',
        '%m/%d/%y',
        '%m-%d-%y'
    ]

    for fmt in formats_to_try:
        try:
            return pd.to_datetime(date_str, format=fmt, errors='raise').strftime('%Y-%m-%d')
        except ValueError:
            pass  # If one format fails, try the next

    # If none of the formats work, return None
    return None


def append_dates_to_file(filepath, dates_to_append):
    """Appends dates to a text file, maintaining sorted order, and creates the file if it does not exist.

    Args:
        filepath (str): The path to the text file.
        dates_to_append (list): A list of date strings to append.
    """
    if not dates_to_append:
        return  # No dates to append

    try:
        # Read the existing content
        try:
            with open(filepath, 'r') as f:
                content = f.read()
        except FileNotFoundError:
            # If the file doesn't exist, create it with empty content
            with open(filepath, 'w') as f:
                f.write('')
            content = ''  # Initialize content to empty string
        # Extract the existing date string
        match = re.search(r'const expiryDatesList = "(.*)";', content)
        if match:
            existing_dates_string = match.group(1)
            existing_dates = [d.strip() for d in existing_dates_string.split(',') if d.strip()]
        else:
            existing_dates = []

        #avoid duplicates
        all_dates = list(set(existing_dates + dates_to_append))
        # Sort the dates *after* combining them
        all_dates.sort()
        # Format dates for the file
        formatted_dates_string = ",".join(all_dates)
        output_string = f"const expiryDatesList = \"{formatted_dates_string}\";"

        # Write the updated content back to the file
        with open(filepath, 'w') as f:
            f.write(output_string)
        print(f"Successfully appended {len(dates_to_append)} dates to {filepath}")
    except Exception as e:
        print(f"Error writing to file {filepath}: {e}")



def main():
    """Main function to coordinate the date processing."""
    text_file_path = '/home/ubuntu/KotakCodes1/expiry_dates.txt'
    csv_file_path = '/home/ubuntu/KotakCodes1/masterfile/ICICImaster.csv'

    # 1. Read dates from the text file
    existing_dates = read_dates_from_file(text_file_path)
    print("Dates read from file:", existing_dates)

    # 2. Read dates from the CSV file
    csv_dates = read_dates_from_csv(csv_file_path)
    if not csv_dates:
        print("Exiting due to error reading CSV file.")
        return  # Exit if there's an error reading the CSV

    # 3. Format dates and find new dates
    new_dates = []
    for csv_date_str in csv_dates:
        formatted_date = format_date(csv_date_str)
        if formatted_date:
            if formatted_date not in existing_dates:
                new_dates.append(formatted_date)
                print("New date found:", formatted_date)
        else:
            print(f"Warning: Could not format date from CSV: {csv_date_str}")

    # 4. Append new dates to the text file
    if new_dates:
        append_dates_to_file(text_file_path, new_dates)
    else:
        print("No new dates to append.")

    # Trigger Telegram bot update with upcoming expiry dates
    try:
        import subprocess
        bot_script = '/home/ubuntu/KotakCodes1/Bot_expirydates.js'
        print(f"Launching Telegram bot notification script: {bot_script}")
        subprocess.run(['node', bot_script], check=True)
    except Exception as e:
        print(f"Error launching Bot_expirydates.js: {e}")

if __name__ == "__main__":
    main()
