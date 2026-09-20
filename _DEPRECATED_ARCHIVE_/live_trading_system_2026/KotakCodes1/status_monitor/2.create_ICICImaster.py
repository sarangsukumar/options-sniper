import csv
import os
import requests
import zipfile
import shutil  # Import the shutil module for robust file/directory operations

def create_csv_from_file(input_filename, output_filename, selected_columns, series_value="FUTURE"):
    """
    Reads data from an input file, extracts specified columns, and writes it to a new CSV file,
    filtering for rows where the 'Series' column matches the specified series_value.

    Args:
        input_filename (str): The name of the input file.
        output_filename (str): The name of the output CSV file to create.
        selected_columns (list): A list of column names to extract.
        series_value (str, optional): The value to filter the 'Series' column by.
            Defaults to "FUTURE".
    """
    try:
        with open(input_filename, 'r', newline='') as infile, \
                open(output_filename, 'w', newline='') as outfile:

            reader = csv.reader(infile)
            writer = csv.writer(outfile)

            header = next(reader)  # Get the header row from the input file
            # Get the indices of the columns to write
            col_indices = [header.index(col) for col in selected_columns]
            series_index = header.index("Series") #get index of Series

            # Write the selected columns as the header in the output CSV
            # Rename headers and convert to lowercase here
            new_header = [
                "stockcodes" if col == "ExchangeCode" else  # Renamed to lowercase "stockcodes"
                "scripcode" if col == "ShortName" else      # Renamed to lowercase "scripcode"
                col.lower()                                  # Convert all other selected column headers to lowercase
                for col in selected_columns
            ]
            writer.writerow(new_header)

            # Write the data rows
            for row in reader:
                # Extract data for the selected columns
                if row[series_index] == series_value: #check if row series is equal to series_value
                    selected_data = [row[i] for i in col_indices]
                    writer.writerow(selected_data)

        print(f"CSV file '{output_filename}' created successfully with rows where Series is '{series_value}'.")

    except FileNotFoundError:
        print(f"Error: File '{input_filename}' not found.")
        raise  # Re-raise the exception to be caught by the outer try-except block
    except ValueError as e:
        print(f"Value Error: {e}")
        raise  # Re-raise the exception
    except Exception as e:
        print(f"An error occurred: {e}")
        raise  # Re-raise the exception



def download_and_process_security_master(output_filename, selected_columns):
    """
    Downloads the Security Master ZIP file, extracts the relevant file,
    cleans up unnecessary files, and creates a CSV file.

    Args:
        output_filename (str): The name of the output CSV file to create.
        selected_columns (list): A list of column names to extract.
    """
    # 1. Download file
    url = "https://directlink.icicidirect.com/NewSecurityMaster/SecurityMaster.zip"
    download_path = "SecurityMaster.zip"

    print(f"Downloading file from: {url} to {download_path}")
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()  # Raise an exception for bad status codes
        with open(download_path, "wb") as file:
            for chunk in response.iter_content(chunk_size=8192):
                file.write(chunk)
        print("Download complete.")
    except requests.exceptions.RequestException as e:
        print(f"Error during download: {e}")
        return  # Exit the function if download fails

    # 2. Unzip folder
    extract_dir = "ICICImaster_data"
    print(f"Unzipping {download_path} to {extract_dir}")
    try:
        # Create the extraction directory if it doesn't exist
        if not os.path.exists(extract_dir):
            os.makedirs(extract_dir)

        with zipfile.ZipFile(download_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
        print("Unzipping complete.")
    except zipfile.BadZipFile as e:
        print(f"Error during unzipping: {e}")
        # Clean up the downloaded file if unzipping failed
        if os.path.exists(download_path):
            os.remove(download_path)
        return  # Exit the function if unzipping fails

    # 3. Delete all files except FONSEScripMaster.txt
    print(f"Deleting files in {extract_dir} except FONSEScripMaster.txt")
    for filename in os.listdir(extract_dir):
        file_path = os.path.join(extract_dir, filename)
        if os.path.isfile(file_path) and filename != "FONSEScripMaster.txt":
            try:
                os.remove(file_path)
                print(f"Deleted: {filename}")
            except OSError as e:
                print(f"Error deleting {filename}: {e}")

    print("File cleanup complete.")

    # 4. Delete the ZIP file
    print(f"Deleting the ZIP file: {download_path}")
    try:
        os.remove(download_path)
        print("ZIP file deleted successfully.")
    except OSError as e:
        print(f"Error deleting the ZIP file {download_path}: {e}")

    # 5. Create the CSV file
    input_filename = os.path.join(extract_dir, "FONSEScripMaster.txt")
    try:
        create_csv_from_file(input_filename, output_filename, selected_columns)
    except Exception as e:
        print(f"Error creating CSV: {e}")
        return # Exit if CSV creation fails. The download/unzip/cleanup already printed errors.

    # 6. Remove the now empty directory
    print(f"Removing directory: {extract_dir}")
    try:
        shutil.rmtree(extract_dir)
        print("Directory removed successfully.")
    except OSError as e:
        print(f"Error removing directory {extract_dir}: {e}")

    # 7. Send Telegram Notification
    send_telegram_status(output_filename)

def send_telegram_status(output_filename):
    try:
        import subprocess
        import pandas as pd
        import datetime
        df = pd.read_csv(output_filename)
        total_rows = len(df)
        
        # Parse dates to find nearest F1 expiry date
        df['parsed_date'] = pd.to_datetime(df['expirydate'], format='%d-%b-%Y', errors='coerce')
        today = pd.Timestamp.now().normalize()
        f1_df = df[df['parsed_date'] >= today].sort_values('parsed_date')
        
        sample = f1_df.iloc[0] if len(f1_df) > 0 else (df.iloc[0] if total_rows > 0 else None)
        now_str = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)).strftime('%Y-%m-%d %H:%M:%S IST')
        
        msg = f"ICICI Master File updated successfully at {now_str}!\nTotal Scrips: {total_rows} contracts downloaded\n"
        if sample is not None:
            msg += f"\nSample Verification (F1 Current Month):\n• Stock Code: {sample.get('stockcodes', '')}\n• Scrip Code: {sample.get('scripcode', '')}\n• Lot Size: {sample.get('lotsize', '')}\n• F1 Expiry Date: {sample.get('expirydate', '')}"
        
        bot_script = "/home/ubuntu/KotakCodes1/status_Info_bot.js"
        print(f"Sending Telegram alert:\n{msg}")
        subprocess.run(['node', bot_script, msg], check=True)
    except Exception as e:
        print(f"Error sending Telegram notification: {e}")


# Usage
output_filename = "/home/ubuntu/KotakCodes1/masterfile/ICICImaster.csv"
selected_columns = ["Token", "InstrumentName", "ShortName", "Series", "ExpiryDate", "LotSize", "ExchangeCode"]
download_and_process_security_master(output_filename, selected_columns)