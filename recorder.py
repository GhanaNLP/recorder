#!/usr/bin/env python3
"""
Audio Recorder
Cross-platform audio recording app with GitHub Gist logging
Auto-remembers volunteer ID and resumes from last position
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog
import json
import base64
import os
import csv
import wave
import threading
import time
import queue
import zipfile
from datetime import datetime
import urllib.request
import urllib.error
import ssl
import re
import hashlib

# Audio handling
try:
    import sounddevice as sd
    import numpy as np
    AUDIO_AVAILABLE = True
except ImportError:
    AUDIO_AVAILABLE = False
    print("Warning: sounddevice/numpy not installed. Audio recording disabled.")

# Configuration
CONFIG_FILE = "config.json"
DATA_FILE = "data.csv"
PROGRESS_DIR = "progress"
RECORDINGS_DIR = "recordings"
EXPORTS_DIR = "exports"

# Available languages
LANGUAGES = ["Twi", "Dagbani", "Ewe"]

# LOGGING TOKEN
ENCODED_GITHUB_TOKEN = "Z2hwXzBMNFFCU0VaOFFQcklvWGNhVTJTOWdQVFhpY0dzM0p1cXR4"

GITHUB_TOKEN = base64.b64decode(ENCODED_GITHUB_TOKEN).decode('utf-8')


class GistLogger:
    """Handles background syncing to GitHub Gist using only stdlib"""
    
    def __init__(self, gist_id, token, volunteer_id, language):
        self.gist_id = gist_id
        self.token = token
        self.volunteer_id = volunteer_id
        self.language = language
        self.last_sync = 0
        self.sync_interval = 30 * 60  # 30 minutes
        self.running = True
        self.queue = queue.Queue()
        self.thread = threading.Thread(target=self._sync_loop, daemon=True)
        self.thread.start()
        
    def _sync_loop(self):
        """Background thread for periodic syncing"""
        while self.running:
            time.sleep(60)  # Check every minute
            if time.time() - self.last_sync >= self.sync_interval:
                self._push_to_gist()
                
    def log_progress(self, data):
        """Queue progress update"""
        self.queue.put(data)
        # Also trigger immediate sync if it's been a while
        if time.time() - self.last_sync >= self.sync_interval:
            threading.Thread(target=self._push_to_gist, daemon=True).start()
            
    def _push_to_gist(self):
        """Update Gist via GitHub API using urllib"""
        try:
            # Collect all pending data
            data = {}
            while not self.queue.empty():
                data = self.queue.get()
                
            if not data:
                return
                
            data['last_update'] = datetime.now().isoformat()
            data['volunteer_id'] = self.volunteer_id
            data['language'] = self.language
            
            filename = f"{self.language}_{self.volunteer_id}_log.json"
            
            url = f"https://api.github.com/gists/{self.gist_id}"
            headers = {
                "Authorization": f"token {self.token}",
                "Content-Type": "application/json",
                "User-Agent": "AudioRecorder/1.0",
                "Accept": "application/vnd.github.v3+json"
            }
            
            payload = {
                "files": {
                    filename: {
                        "content": json.dumps(data, indent=2)
                    }
                }
            }
            
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode('utf-8'),
                headers=headers,
                method='PATCH'
            )
            
            # Handle SSL context for older Python versions
            context = ssl.create_default_context()
            
            with urllib.request.urlopen(req, context=context, timeout=30) as response:
                if response.status == 200:
                    self.last_sync = time.time()
                    print(f"Gist updated: {datetime.now()}")
                    
        except Exception as e:
            print(f"Gist sync failed: {e}")
            
    def force_sync(self):
        """Force immediate sync"""
        self._push_to_gist()
        
    def stop(self):
        self.running = False
        self.force_sync()


class AudioRecorder:
    """Handles audio recording with sounddevice"""
    
    def __init__(self, sample_rate=16000):
        self.sample_rate = sample_rate
        self.channels = 1
        self.recording = False
        self.frames = []
        self.stream = None
        
    def start_recording(self):
        if not AUDIO_AVAILABLE:
            raise RuntimeError("Audio libraries not available")
            
        self.recording = True
        self.frames = []
        
        def callback(indata, frames, time_info, status):
            if self.recording:
                self.frames.append(indata.copy())
                
        self.stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype=np.int16,
            callback=callback,
            blocksize=1024
        )
        self.stream.start()
        
    def stop_recording(self):
        if not self.recording:
            return None
            
        self.recording = False
        self.stream.stop()
        self.stream.close()
        
        if self.frames:
            return np.concatenate(self.frames, axis=0)
        return None
        
    def save_audio(self, audio_data, filepath):
        """Save as WAV"""
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        # Save as WAV (universally compatible)
        wav_path = filepath.replace('.opus', '.wav')
        with wave.open(wav_path, 'wb') as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(self.sample_rate)
            wf.writeframes(audio_data.tobytes())
            
        return wav_path


class DataManager:
    """Manages CSV data - each row is one unit"""
    
    def __init__(self, csv_path):
        self.rows = []
        
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader):
                self.rows.append({
                    'global_idx': idx,
                    'id': row.get('id', idx),
                    'text': row.get('text', row.get('paragraph', ''))
                })
                
    def get_all_rows(self):
        """Get all rows for processing"""
        return self.rows


class ProgressManager:
    """Handles local save/resume functionality"""
    
    def __init__(self, volunteer_id, language):
        self.volunteer_id = volunteer_id
        self.language = language
        self.filepath = os.path.join(PROGRESS_DIR, f"{language}_{volunteer_id}_progress.json")
        os.makedirs(PROGRESS_DIR, exist_ok=True)
        
        self.data = {
            'volunteer_id': volunteer_id,
            'language': language,
            'completed_rows': [],
            'current_index': 0,
            'recordings': {},  # row_idx: filepath
            'started_at': datetime.now().isoformat(),
            'last_session': None
        }
        
        self.load()
        
    def load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r') as f:
                    loaded = json.load(f)
                    self.data.update(loaded)
            except Exception as e:
                print(f"Error loading progress: {e}")
                
    def save(self):
        self.data['last_session'] = datetime.now().isoformat()
        with open(self.filepath, 'w') as f:
            json.dump(self.data, f, indent=2)
            
    def mark_complete(self, row_idx, filepath):
        if row_idx not in self.data['completed_rows']:
            self.data['completed_rows'].append(row_idx)
        self.data['recordings'][str(row_idx)] = filepath
        self.save()
        
    def set_current(self, idx):
        self.data['current_index'] = idx
        self.save()
        
    def is_complete(self, row_idx):
        return row_idx in self.data['completed_rows']


class RecorderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Audio Recorder")
        self.root.geometry("900x700")
        
        # Setup directories
        for d in [PROGRESS_DIR, RECORDINGS_DIR, EXPORTS_DIR]:
            os.makedirs(d, exist_ok=True)
            
        # State
        self.data_manager = None
        self.progress = None
        self.recorder = AudioRecorder()
        self.gist_logger = None
        self.all_rows = []
        self.current_pos = 0
        self.is_recording = False
        self.current_audio = None
        
        # Volunteer info
        self.volunteer_id = None
        self.language = None
        
        # Load config
        self.config = self._load_config()
        
        # Check for auto-login with saved credentials
        saved_id = self.config.get('saved_volunteer_id', '')
        saved_lang = self.config.get('saved_language', '')
        
        if saved_id and saved_lang and self._try_auto_login(saved_id, saved_lang):
            pass
        else:
            # Show setup UI
            self._build_setup_ui()
        
        # Handle close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        
    def _load_config(self):
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        return {
            'gist_id': '', 
            'sample_rate': 16000, 
            'saved_volunteer_id': '',
            'saved_language': ''
        }
        
    def _save_config(self):
        with open(CONFIG_FILE, 'w') as f:
            json.dump(self.config, f, indent=2)
        
    def _try_auto_login(self, volunteer_id, language):
        """Try to auto-login with saved credentials"""
        try:
            # Validate data file exists
            if not os.path.exists(DATA_FILE):
                return False
            
            # Set volunteer info
            self.volunteer_id = volunteer_id
            self.language = language
            
            # Load data
            self.data_manager = DataManager(DATA_FILE)
            self.all_rows = self.data_manager.get_all_rows()
            
            if not self.all_rows:
                return False
            
            # Initialize progress
            self.progress = ProgressManager(volunteer_id, language)
            
            # Initialize gist logger if gist_id provided
            gist_id = self.config.get('gist_id', '')
            if gist_id:
                self.gist_logger = GistLogger(gist_id, GITHUB_TOKEN, volunteer_id, language)
            
            # Resume from where they left off
            self.current_pos = self.progress.data['current_index']
            if self.current_pos >= len(self.all_rows):
                self.current_pos = 0
            
            # Check for existing progress
            completed = len(self.progress.data['completed_rows'])
            total = len(self.all_rows)
            
            # Build main UI directly (skip login)
            self._build_main_ui()
            self._update_display()
            
            # Show welcome back message if returning
            if completed > 0:
                messagebox.showinfo("Welcome Back!", 
                    f"Welcome back {self.volunteer_id}!\n\n"
                    f"Language: {self.language}\n"
                    f"Progress: {completed}/{total} rows completed\n"
                    f"Resuming from row {self.current_pos + 1}")
            
            # Start background logging
            self._update_gist_log()
            
            return True
            
        except Exception as e:
            print(f"Auto-login failed: {e}")
            # Clear saved credentials if invalid
            self.config['saved_volunteer_id'] = ''
            self.config['saved_language'] = ''
            self._save_config()
            return False
        
    def _build_setup_ui(self):
        """Initial setup UI to get volunteer ID and select language"""
        self.setup_frame = ttk.Frame(self.root, padding=50)
        self.setup_frame.place(relx=0.5, rely=0.5, anchor='center')
        
        ttk.Label(self.setup_frame, text="Audio Recorder Setup", 
                 font=('Arial', 20, 'bold')).pack(pady=10)
        
        # Volunteer ID input
        ttk.Label(self.setup_frame, text="Enter Your Volunteer ID/Name:", 
                 font=('Arial', 12)).pack(pady=(20, 5))
        
        self.volunteer_entry = ttk.Entry(self.setup_frame, width=40, font=('Arial', 12))
        self.volunteer_entry.pack(pady=5)
        
        # Pre-fill if saved
        saved_id = self.config.get('saved_volunteer_id', '')
        if saved_id:
            self.volunteer_entry.insert(0, saved_id)
        
        # Language selection dropdown
        ttk.Label(self.setup_frame, text="Select Language:", 
                 font=('Arial', 12)).pack(pady=(20, 5))
        
        self.language_var = tk.StringVar()
        self.language_dropdown = ttk.Combobox(
            self.setup_frame, 
            textvariable=self.language_var,
            values=LANGUAGES,
            width=37,
            font=('Arial', 11),
            state='readonly'
        )
        self.language_dropdown.pack(pady=5)
        
        # Pre-select if saved
        saved_lang = self.config.get('saved_language', '')
        if saved_lang and saved_lang in LANGUAGES:
            self.language_var.set(saved_lang)
        else:
            self.language_var.set(LANGUAGES[0])  # Default to first language
        
        # Gist ID input (optional)
        ttk.Label(self.setup_frame, text="Gist ID (optional, for sync):", 
                 font=('Arial', 10)).pack(pady=(15, 5))
        
        self.gist_entry = ttk.Entry(self.setup_frame, width=40, font=('Arial', 10))
        self.gist_entry.pack(pady=5)
        
        # Pre-fill if saved
        saved_gist = self.config.get('gist_id', '')
        if saved_gist:
            self.gist_entry.insert(0, saved_gist)
        
        # Start button
        ttk.Button(self.setup_frame, text="Start Recording Session", 
                  command=self._on_setup_complete).pack(pady=30)
        
        # Status label
        self.status_label = ttk.Label(self.setup_frame, text="", foreground='red')
        self.status_label.pack()
        
    def _on_setup_complete(self):
        """Validate setup and start recording session"""
        volunteer_id = self.volunteer_entry.get().strip()
        language = self.language_var.get()
        gist_id = self.gist_entry.get().strip()
        
        if not volunteer_id:
            self.status_label.config(text="Please enter your Volunteer ID")
            return
            
        if not language:
            self.status_label.config(text="Please select a language")
            return
        
        try:
            # Validate data file exists
            if not os.path.exists(DATA_FILE):
                messagebox.showerror("Error", f"Data file not found: {DATA_FILE}")
                return
            
            # Set volunteer info
            self.volunteer_id = volunteer_id
            self.language = language
            
            # Load data
            self.data_manager = DataManager(DATA_FILE)
            self.all_rows = self.data_manager.get_all_rows()
            
            if not self.all_rows:
                messagebox.showerror("Error", "No data found in CSV file")
                return
            
            # Initialize progress
            self.progress = ProgressManager(volunteer_id, language)
            
            # Initialize gist logger if gist_id provided
            if gist_id:
                self.gist_logger = GistLogger(gist_id, GITHUB_TOKEN, volunteer_id, language)
                # Save gist_id for future
                self.config['gist_id'] = gist_id
            
            # Save volunteer_id and language for future
            self.config['saved_volunteer_id'] = volunteer_id
            self.config['saved_language'] = language
            self._save_config()
            
            # Resume from where they left off
            self.current_pos = self.progress.data['current_index']
            if self.current_pos >= len(self.all_rows):
                self.current_pos = 0
            
            # Switch to main UI
            self.setup_frame.destroy()
            self._build_main_ui()
            self._update_display()
            
            # Start background logging
            self._update_gist_log()
            
        except Exception as e:
            self.status_label.config(text=f"Error: {str(e)}")
            import traceback
            traceback.print_exc()
            
    def _build_main_ui(self):
        # Main container
        main = ttk.Frame(self.root, padding=20)
        main.pack(fill='both', expand=True)
        
        # Header with progress
        header = ttk.Frame(main)
        header.pack(fill='x', pady=(0, 20))
        
        header_left = ttk.Frame(header)
        header_left.pack(side='left')
        
        ttk.Label(header_left, text=f"Volunteer: {self.volunteer_id}", 
                 font=('Arial', 12, 'bold')).pack(anchor='w')
        ttk.Label(header_left, text=f"Language: {self.language}", 
                 font=('Arial', 10), foreground='blue').pack(anchor='w')
        
        # Switch User button
        ttk.Button(header, text="Switch User", 
                  command=self._logout).pack(side='left', padx=10)
        
        self.progress_var = tk.StringVar(value="Progress: 0/0")
        ttk.Label(header, textvariable=self.progress_var, 
                 font=('Arial', 11)).pack(side='right')
        
        # Progress bar
        self.progress_bar = ttk.Progressbar(main, mode='determinate')
        self.progress_bar.pack(fill='x', pady=(0, 20))
        
        # Text display
        text_frame = ttk.LabelFrame(main, text="Current Text", padding=10)
        text_frame.pack(fill='both', expand=True, pady=10)
        
        self.text_display = scrolledtext.ScrolledText(
            text_frame, wrap=tk.WORD, font=('Arial', 14), height=10
        )
        self.text_display.pack(fill='both', expand=True)
        
        # Row info
        self.row_counter = ttk.Label(main, text="", font=('Arial', 10))
        self.row_counter.pack(pady=5)
        
        # Control buttons
        controls = ttk.Frame(main)
        controls.pack(pady=20)
        
        self.record_btn = tk.Button(
            controls, text="● Record", command=self._toggle_recording,
            bg='red', fg='white', font=('Arial', 12, 'bold'),
            width=12, height=2
        )
        self.record_btn.pack(side='left', padx=5)
        
        ttk.Button(controls, text="▶ Play", command=self._play_current).pack(side='left', padx=5)
        ttk.Button(controls, text="⏮ Prev", command=self._prev_row).pack(side='left', padx=5)
        ttk.Button(controls, text="⏭ Next", command=self._next_row).pack(side='left', padx=5)
        
        # Status and export
        status_frame = ttk.Frame(main)
        status_frame.pack(fill='x', pady=10)
        
        self.status_text = tk.StringVar(value="Ready")
        ttk.Label(status_frame, textvariable=self.status_text).pack(side='left')
        
        ttk.Button(status_frame, text="Export ZIP", 
                  command=self._export_zip).pack(side='right')
        ttk.Button(status_frame, text="Force Sync", 
                  command=self._force_sync).pack(side='right', padx=5)
        
        # Auto-save indicator
        self.save_indicator = ttk.Label(main, text="", foreground='green')
        self.save_indicator.pack(pady=5)
        
    def _logout(self):
        """Clear saved user and return to setup screen"""
        if messagebox.askyesno("Switch User", "Are you sure you want to switch to a different user?"):
            self.config['saved_volunteer_id'] = ''
            self.config['saved_language'] = ''
            self._save_config()
            
            if self.gist_logger:
                self.gist_logger.stop()
                
            # Destroy main window and rebuild
            for widget in self.root.winfo_children():
                widget.destroy()
                
            # Reset state
            self.data_manager = None
            self.progress = None
            self.gist_logger = None
            self.all_rows = []
            self.current_pos = 0
            self.volunteer_id = None
            self.language = None
            
            self._build_setup_ui()
        
    def _update_display(self):
        if not self.all_rows or self.current_pos >= len(self.all_rows):
            return
            
        row_data = self.all_rows[self.current_pos]
        
        # Update progress
        total = len(self.all_rows)
        completed = len(self.progress.data['completed_rows'])
        self.progress_var.set(f"Progress: {completed}/{total} (Row {self.current_pos + 1}/{total})")
        self.progress_bar['maximum'] = total
        self.progress_bar['value'] = completed
        
        # Display text
        self.text_display.delete('1.0', tk.END)
        self.text_display.insert(tk.END, row_data['text'])
        
        # Update row info
        global_idx = row_data['global_idx']
        self.row_counter.config(
            text=f"Global ID: {global_idx} | Language: {self.language} | "
                 f"Status: {'✓ Recorded' if self.progress.is_complete(global_idx) else 'Pending'}"
        )
        
        # Update button states
        is_done = self.progress.is_complete(global_idx)
        if is_done:
            self.record_btn.config(text="✓ Re-record", bg='orange')
        else:
            self.record_btn.config(text="● Record", bg='red')
            
    def _toggle_recording(self):
        if not AUDIO_AVAILABLE:
            messagebox.showerror("Error", "Audio libraries not installed")
            return
            
        if self.is_recording:
            self._stop_recording()
        else:
            self._start_recording()
            
    def _start_recording(self):
        self.is_recording = True
        self.record_btn.config(text="⏹ Stop", bg='darkred')
        self.status_text.set("Recording...")
        self.recorder.start_recording()
        
    def _stop_recording(self):
        self.is_recording = False
        self.record_btn.config(text="Processing...", state='disabled')
        
        audio_data = self.recorder.stop_recording()
        
        if audio_data is not None and len(audio_data) > 0:
            # Save file with language and volunteer in path
            row_data = self.all_rows[self.current_pos]
            filename = f"row_{row_data['global_idx']}.wav"
            filepath = os.path.join(RECORDINGS_DIR, f"{self.language}_{self.volunteer_id}", filename)
            
            saved_path = self.recorder.save_audio(audio_data, filepath)
            
            # Update progress
            self.progress.mark_complete(row_data['global_idx'], saved_path)
            self.progress.set_current(self.current_pos)
            
            # Visual feedback
            self.save_indicator.config(text=f"Saved: {filename}")
            self.root.after(2000, lambda: self.save_indicator.config(text=""))
            
            # Log to gist
            self._update_gist_log()
            
        self.record_btn.config(text="● Record", bg='red', state='normal')
        self.status_text.set("Ready")
        self._update_display()
        
    def _play_current(self):
        """Play back current row recording if exists"""
        if not AUDIO_AVAILABLE:
            return
            
        row_data = self.all_rows[self.current_pos]
        if not self.progress.is_complete(row_data['global_idx']):
            messagebox.showinfo("Playback", "No recording for this row yet!")
            return
            
        filepath = self.progress.data['recordings'].get(str(row_data['global_idx']))
        if not filepath or not os.path.exists(filepath):
            messagebox.showerror("Error", "Recording file not found!")
            return
            
        try:
            import soundfile as sf
            data, samplerate = sf.read(filepath)
            sd.play(data, samplerate)
        except Exception as e:
            # Fallback: use wave
            try:
                with wave.open(filepath, 'rb') as wf:
                    data = wf.readframes(wf.getnframes())
                    import array
                    audio_array = array.array('h', data)
                    sd.play(audio_array, wf.getframerate())
            except Exception as e2:
                print(f"Playback error: {e2}")
                messagebox.showerror("Error", f"Could not play recording: {e2}")
                
    def _next_row(self):
        if self.current_pos < len(self.all_rows) - 1:
            self.current_pos += 1
            self.progress.set_current(self.current_pos)
            self._update_display()
        else:
            messagebox.showinfo("Complete", "You've reached the end! Click Export ZIP to submit.")
            
    def _prev_row(self):
        if self.current_pos > 0:
            self.current_pos -= 1
            self.progress.set_current(self.current_pos)
            self._update_display()
            
    def _update_gist_log(self):
        """Send current progress to Gist"""
        if not self.gist_logger:
            return
            
        completed = len(self.progress.data['completed_rows'])
        total = len(self.all_rows)
        
        log_data = {
            'volunteer_id': self.volunteer_id,
            'language': self.language,
            'completed_rows': completed,
            'total_rows': total,
            'percentage': round((completed / total) * 100, 1) if total > 0 else 0,
            'current_row_idx': self.current_pos,
            'session_started': self.progress.data['started_at'],
            'last_row_recorded': max(self.progress.data['completed_rows']) 
                                if self.progress.data['completed_rows'] else None
        }
        
        self.gist_logger.log_progress(log_data)
        
    def _force_sync(self):
        self._update_gist_log()
        if self.gist_logger:
            self.gist_logger.force_sync()
        messagebox.showinfo("Sync", "Progress synced to GitHub Gist")
        
    def _export_zip(self):
        """Create ZIP with all recordings and metadata"""
        if not self.progress.data['completed_rows']:
            messagebox.showwarning("Export", "No recordings to export yet!")
            return
            
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_name = f"submission_{self.language}_{self.volunteer_id}_{timestamp}.zip"
        zip_path = os.path.join(EXPORTS_DIR, zip_name)
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Add recordings
            for row_idx, filepath in self.progress.data['recordings'].items():
                if os.path.exists(filepath):
                    # Include language in archive path
                    arcname = f"{self.language}/{os.path.basename(filepath)}"
                    zf.write(filepath, arcname)
                    
            # Add metadata
            metadata = {
                'volunteer_id': self.volunteer_id,
                'language': self.language,
                'export_date': timestamp,
                'rows_completed': len(self.progress.data['completed_rows']),
                'total_rows': len(self.all_rows),
                'assignments': [
                    {
                        'global_idx': r['global_idx'],
                        'id': r['id'],
                        'text': r['text'],
                        'language': self.language,
                        'audio_file': os.path.basename(
                            self.progress.data['recordings'].get(str(r['global_idx']), '')
                        )
                    }
                    for r in self.all_rows
                    if self.progress.is_complete(r['global_idx'])
                ]
            }
            zf.writestr(f'{self.language}_metadata.json', json.dumps(metadata, indent=2))
            
        messagebox.showinfo("Export Complete", 
                          f"Created: {zip_path}\n\n"
                          f"Language: {self.language}\n"
                          f"Please send this file to your project manager.")
                          
    def _on_close(self):
        if self.gist_logger:
            self._update_gist_log()
            self.gist_logger.stop()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = RecorderApp(root)
    root.mainloop()
