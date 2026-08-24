import csv
import os
import requests
import zipfile
import shutil  # Import the shutil module for robust file/directory operations

def create_csv_from_file(input_filename, output_filename, selected_columns, series_value="OPTION"): # Changed default to "OPTION"
    """
    Reads data from an input file, extracts specified columns, and writes it to a new CSV file,
    filtering for rows where the 'Series' column matches the specified series_value.

    Args:
        input_filename (str): The name of the input file.
        output_filename (str): The name of the output CSV file to create.
        selected_columns (list): A list of column names to extract.
        series_value (str, optional): The value to filter the 'Series' column by.
            Defaults to "OPTION".
    """
    try:
        with open(input_filename, 'r', newline='') as infile, \
                open(output_filename, 'w', newline='') as outfile:

            reader = csv.reader(infile)
            writer = csv.writer(outfile)

            header = next(reader)  # Get the header row from the input file

            # Get the indices of the columns to write
            # We need to explicitly add 'StrikePrice' and 'OptionType' to selected_columns for their indices
            # and then handle them separately if they are not directly present but derived
            
            # Map existing header names to desired output names
            header_map = {
                "Token": "token",
                "InstrumentName": "instrumentname",
                "ShortName": "scripcode",
                "Series": "series",
                "ExpiryDate": "ExpiryDate", # Corrected typo based on your request "expirrydae"
                "LotSize": "lotsize",
                "ExchangeCode": "stockcodes", # Renamed ExchangeCode to stockcodes as per your original output
                "StrikePrice": "StrikePrice", # New column
                "OptionType": "OptionType" # New column
            }

            # Create the new header for the output CSV
            # This ensures the order of columns in the output matches `selected_columns`
            new_header = [header_map.get(col, col) for col in selected_columns]
            writer.writerow(new_header)

            # Get indices for required columns from the original header
            col_indices = {}
            for col in selected_columns:
                try:
                    col_indices[col] = header.index(col)
                except ValueError:
                    # Handle cases where 'StrikePrice' or 'OptionType' might not be directly in the header
                    # We'll extract them from 'InstrumentName' if needed.
                    if col == "StrikePrice" or col == "OptionType":
                        continue # Will be handled below
                    else:
                        raise ValueError(f"Column '{col}' not found in input file header.")

            series_index = header.index("Series") #get index of Series

            # Write the data rows
            for row in reader:
                # Filter based on series_value (now "OPTION")
                if row[series_index] == series_value:
                    selected_data = []
                    # Populate selected_data based on the order of `selected_columns`
                    for col_name in selected_columns:
                        if col_name in col_indices:
                            selected_data.append(row[col_indices[col_name]])
                        elif col_name == "StrikePrice":
                            # Extract StrikePrice from InstrumentName if available
                            strike_price = ""
                            instrument_name = row[header.index("InstrumentName")]
                            # Assuming format like NIFTY24JUL19500CE, NIFTY24JUL19500PE
                            # The strike price is usually before CE/PE
                            # We need to find the numerical part before the last two letters (CE/PE)
                            import re
                            match = re.search(r'(\d+)(CE|PE)$', instrument_name)
                            if match:
                                strike_price = match.group(1)
                            selected_data.append(strike_price)
                        elif col_name == "OptionType":
                            # Extract OptionType (CE/PE) from InstrumentName if available
                            option_type = ""
                            instrument_name = row[header.index("InstrumentName")]
                            match = re.search(r'(CE|PE)$', instrument_name)
                            if match:
                                option_type = match.group(1)
                            selected_data.append(option_type)
                        else:
                            selected_data.append("") # Append empty if column not found and not a derived column

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
        # Pass series_value="OPTION" explicitly to create_csv_from_file
        create_csv_from_file(input_filename, output_filename, selected_columns, series_value="OPTION")
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
        # Not a critical failure, so don't exit. The program has done its main work.


# Usage
output_filename = "/home/ubuntu/KotakCodes1/masterfile/ICICImaster_options.csv"
selected_columns = [
    "Token",
    "InstrumentName",
    "ShortName",
    "Series",
    "ExpiryDate",
    "LotSize",
    "ExchangeCode",
    "StrikePrice",  # Added new column
    "OptionType"    # Added new column
]
download_and_process_security_master(output_filename, selected_columns)