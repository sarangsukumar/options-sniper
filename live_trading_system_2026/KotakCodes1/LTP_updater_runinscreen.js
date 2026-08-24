const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

// --- Configuration ---
// Full path to your LTP_updater.py script
//const LTP_UPDATER_SCRIPT_PATH = "/home/ubuntu/KotakCodes1/LTP_updater_unified_optimized2.py";
const LTP_UPDATER_SCRIPT_PATH = "/home/ubuntu/KotakCodes1/LTP_updater_redis.py";

// Base name for the screen session. Will be appended with a timestamp if not provided via CLI.
const BASE_SCREEN_SESSION_NAME = "ltp_updater_session";

// Log file for this wrapper script's actions
const LOG_FILE = "/home/ubuntu/KotakCodes1/run_ltp_in_screen.log";

// Timeout duration for the screen session.
// This directly maps to the 'timeout' command's duration string (e.g., '3h', '180m', '10800s').
const TIMEOUT_DURATION = "3h";

// --- Configure Logging ---
// Ensure the logs directory exists if LOG_FILE is not in current working directory
const logDir = path.dirname(LOG_FILE);
if (!fs.existsSync(logDir)) {
    fs.mkdirSync(logDir, { recursive: true });
}

const logStream = fs.createWriteStream(LOG_FILE, { flags: 'a' });

function log(level, message) {
    const timestamp = new Date().toISOString().replace(/T/, ' ').replace(/\..+/, '');
    const logMessage = `${timestamp} - ${level.toUpperCase()} - ${message}`;
    console.log(logMessage); // Also print to console
    logStream.write(logMessage + '\n');
}

/**
 * Starts a given script in a detached screen session.
 * @param {string} scriptPath The path to the script to run.
 * @param {string} sessionName The name for the screen session.
 * @param {string[]} scriptArgs An array of arguments to pass to the script.
 * @param {string} timeoutDuration The timeout duration string (e.g., '3h', '180m').
 * @returns {Promise<boolean>} A promise that resolves to true if successful, false otherwise.
 */
async function startScriptInScreen(scriptPath, sessionName, scriptArgs, timeoutDuration) {
    // Construct the command that will run inside the screen session.
    // Use 'bash -c' to ensure 'timeout' command is available and
    // 'exec' to replace the shell process with the actual command,
    // which helps with proper signal handling (e.g., timeout ending).
    const commandToRun = `timeout ${timeoutDuration} python3 ${scriptPath} ${scriptArgs.join(' ')}`;
    const screenCommandArgs = ['-dmS', sessionName, 'bash', '-c', `exec ${commandToRun}`];

    log('info', `Attempting to start '${commandToRun}' in new detached screen session '${sessionName}'.`);

    return new Promise((resolve) => {
        const screenProcess = spawn('screen', screenCommandArgs, {
            stdio: 'ignore', // Do not inherit stdio for detached screen
            detached: true // Important for keeping the child process running in the background
        });

        screenProcess.on('close', (code) => {
            if (code === 0) {
                log('info', `Screen session for '${scriptPath}' with name '${sessionName}' started successfully.`);
                resolve(true);
            } else {
                log('error', `Screen process for '${scriptPath}' with name '${sessionName}' exited with code ${code}.`);
                log('error', `This might happen if a screen session with the exact same name was created concurrently.`);
                resolve(false);
            }
        });

        screenProcess.on('error', (err) => {
            log('error', `Failed to spawn screen process for session '${sessionName}': ${err.message}`);
            resolve(false);
        });

        // Detach the child process from the parent
        screenProcess.unref();
    });
}

// --- Main execution ---
async function main() {
    // Arguments for this wrapper script.
    // The first argument (process.argv[2]) will be used as the screen session name, if provided.
    const customSessionName = process.argv[2];
    const scriptArgs = process.argv.slice(3); // Remaining arguments are for LTP_updater.py

    let screenSessionName;
    if (customSessionName) {
        // If the customSessionName starts with '--', it's an argument for the inner script, not a session name.
        // This handles cases where user might omit session name and pass arguments directly.
        if (customSessionName.startsWith('--') || customSessionName.startsWith('-')) {
            screenSessionName = `${BASE_SCREEN_SESSION_NAME}_${new Date().toISOString().replace(/[:.-]/g, '_')}`;
            // If it was an argument, put it back into scriptArgs
            scriptArgs.unshift(customSessionName);
            log('info', `First argument '${customSessionName}' treated as script argument. Generated unique session name: '${screenSessionName}'`);
        } else {
            screenSessionName = customSessionName;
            log('info', `Using custom screen session name: '${screenSessionName}'`);
        }
    } else {
        // Generate a unique session name using a timestamp for "different names"
        screenSessionName = `${BASE_SCREEN_SESSION_NAME}_${new Date().toISOString().replace(/[:.-]/g, '_')}`;
        log('info', `No custom screen session name provided. Generated unique name: '${screenSessionName}'`);
    }

    log('info', `Starting screen wrapper for '${LTP_UPDATER_SCRIPT_PATH}' with session name '${screenSessionName}' and args for updater: ${scriptArgs.join(' ')}`);

    try {
        const started = await startScriptInScreen(LTP_UPDATER_SCRIPT_PATH, screenSessionName, scriptArgs, TIMEOUT_DURATION);
        if (started) {
            log('info', `'${LTP_UPDATER_SCRIPT_PATH}' is now running in detached screen session '${screenSessionName}' and will terminate after ${TIMEOUT_DURATION}.`);
            log('info', `You can attach to this session using: screen -r ${screenSessionName}`);
            log('info', `You can list active sessions using: screen -ls`);
        } else {
            log('error', `Failed to start '${LTP_UPDATER_SCRIPT_PATH}' in screen session '${screenSessionName}'. Check logs for details.`);
            process.exit(1); // Exit with error
        }
    } catch (e) {
        log('error', `An unexpected error occurred: ${e.message}`);
        process.exit(1); // Exit with error
    } finally {
        logStream.end(); // Close the log file stream
    }
}

main();