# Recorder

Welcome! This tool helps you record audio in your local language for our dataset. Your recordings will help improve language technology and digital accessibility. Follow the steps below to get started.

## How to Start

Watch video tutorial here: https://youtu.be/lZnr72CxsRo

1. **Install Python**:

   Make sure you have Python installed on your computer. You can download it from [python.org](https://www.python.org/).

2. **Clone the Repository**:

   First, download the project files to your computer. Open your terminal and run:

   ```
   git clone https://github.com/GhanaNLP/recorder.git
   cd recorder
   ```

3. **Setup the App**:

   Install the necessary dependencies by running the following command inside the project folder:

   ```
   pip install -r requirements.txt
   ```

4. **Launch the Recorder**:

   Start the application by running:

   ```
   python recorder.py
   ```
   On `MacBook` if run into `ModuleNotFoundError: No module named '_tkinter'` issue then install

   ```sh
   brew install python-tk
   ```

5. **Select Your Language**:

   When the app opens, select the language you are recording for (e.g., **Twi**, **Ewe**, or **Dagbani**) from the menu to load the corresponding dataset.

## How to Record

- **Read the Text**: You will see a paragraph or sentence on the screen based on your selected language.
- **Record**: Click the **Record** button and read the text clearly. Use a quiet environment if possible.
- **Review**: You can play back your recording to make sure it sounds good and there are no loud background noises.
- **Save & Next**: Once you are satisfied, move to the next sentence. The app saves your progress automatically.

## Useful Features

- **Resume Anytime**: If you close the app or your computer restarts, simply relaunch and select the same language to pick up exactly where you left off.
- **Bundled Dataset**: All required text is already included in the repository, so you can start contributing immediately.
- **Automatic Sync**: Your progress is periodically backed up to our secure logs to ensure no work is lost.
- **Offline Support**: You can record without an internet connection; the app will sync your progress the next time you are online.

## Finishing Your Task

When you have finished all your assigned recordings:

1. Click the **Export** button in the app.
2. The app will generate a `.zip` file in the `exports/` folder.
3. Send this ZIP file to your project coordinator via email or the agreed-upon platform.

## File Locations

- `recordings/`: This folder stores your individual audio clips.
- `exports/`: This is where your final submission package (`.zip`) will appear.

**Thank you for your contribution to language speech collection for Ghanaian languages!**
