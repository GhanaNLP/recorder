#!/usr/bin/env python3
"""
Audio Recorder
Cross-platform audio recording app with GitHub Gist logging
Auto-remembers volunteer code and resumes from last position
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
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

class GistLogger:
    """Handles background syncing to GitHub Gist using only stdlib"""
    
    def __init__(self, gist_id, token, volunteer_id):
        self.gist_id = gist_id
        self.token = token
        self.volunteer_id = volunteer_id
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
            
            filename = f"volunteer_{self.volunteer_id}_log.json"
            
            url = f"https://api.github.com/gists/{self.gist_id}"
            headers = {
                "Authorization": f"token {self.token}",
                "Content-Type": "application/json",
                "User-Agent": "TwiRecorder/1.0",
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
        """Save as WAV (Opus requires external lib, structed for easy swap)"""
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
    """Manages CSV data - each row is one unit (no sentence splitting)"""
    
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
                
    def get_assigned_indices(self, start, count):
        """Get slice of rows for volunteer"""
        end = min(start + count, len(self.rows))
        return self.rows[start:end]

class ProgressManager:
    """Handles local save/resume functionality"""
    
    def __init__(self, volunteer_code):
        self.code = volunteer_code
        self.filepath = os.path.join(PROGRESS_DIR, f"{volunteer_code}_progress.json")
        os.makedirs(PROGRESS_DIR, exist_ok=True)
        
        self.data = {
            'volunteer_code': volunteer_code,
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
        self.assigned_rows = []
        self.current_pos = 0
        self.is_recording = False
        self.current_audio = None
        
        # Volunteer info
        self.token = None
        self.start_idx = None
        self.count = None
        self.volunteer_name = None
        self.volunteer_code = None
        
        # Load config (includes saved volunteer code)
        self.config = self._load_config()
        
        # Try auto-login if code was saved
        saved_code = self.config.get('saved_volunteer_code', '')
        if saved_code and self._try_auto_login(saved_code):
            # Successfully resumed with saved code
            pass
        else:
            # Show login UI
            self._build_login_ui()
        
        # Handle close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        
    def _load_config(self):
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        return {'gist_id': '', 'sample_rate': 16000, 'saved_volunteer_code': ''}
        
    def _save_config(self):
        with open(CONFIG_FILE, 'w') as f:
            json.dump(self.config, f, indent=2)
        
    def _decode_volunteer_code(self, code):
        """Decode base64 JSON from volunteer code"""
        try:
            # Remove VOL- prefix if present
            if code.startswith('VOL-'):
                code = code[4:]
                
            # Pad base64
            padding = 4 - len(code) % 4
            if padding != 4:
                code += '=' * padding
                
            decoded = base64.b64decode(code).decode('utf-8')
            return json.loads(decoded)
        except Exception as e:
            raise ValueError(f"Invalid code format: {e}")
            
    def _try_auto_login(self, code):
        """Try to auto-login with saved code"""
        try:
            # Validate data file exists first
            if not os.path.exists(DATA_FILE):
                return False
                
            # Decode credentials
            creds = self._decode_volunteer_code(code)
            self.token = creds['t']
            self.start_idx = creds['s']
            self.count = creds['c']
            self.volunteer_name = creds['v']
            self.volunteer_code = code
            
            # Initialize data manager
            self.data_manager = DataManager(DATA_FILE)
            self.assigned_rows = self.data_manager.get_assigned_indices(
                self.start_idx, self.count
            )
            
            if not self.assigned_rows:
                return False
                
            # Initialize progress (this loads existing progress)
            self.progress = ProgressManager(code)
            self.gist_logger = GistLogger(
                self.config.get('gist_id'), 
                self.token, 
                self.volunteer_name
            )
            
            # Resume from where they left off
            self.current_pos = self.progress.data['current_index']
            if self.current_pos >= len(self.assigned_rows):
                self.current_pos = 0
                
            # Build main UI directly (skip login)
            self._build_main_ui()
            self._update_display()
            
            # Show resume notification
            completed = len(self.progress.data['completed_rows'])
            total = len(self.assigned_rows)
            if completed > 0:
                messagebox.showinfo("Welcome Back!", 
                    f"Welcome back {self.volunteer_name}!\n\n"
                    f"Progress: {completed}/{total} rows completed\n"
                    f"Resuming from row {self.current_pos + 1}")
            
            # Start background logging
            self._update_gist_log()
            
            return True
            
        except Exception as e:
            print(f"Auto-login failed: {e}")
            # Clear saved code if invalid
            self.config['saved_volunteer_code'] = ''
            self._save_config()
            return False
            
    def _build_login_ui(self):
        self.login_frame = ttk.Frame(self.root, padding=50)
        self.login_frame.place(relx=0.5, rely=0.5, anchor='center')
        
        ttk.Label(self.login_frame, text="Audio Recorder", 
                 font=('Arial', 20, 'bold')).pack(pady=10)
        
        ttk.Label(self.login_frame, text="Enter Volunteer Code", 
                 font=('Arial', 14)).pack(pady=20)
        
        self.code_entry = ttk.Entry(self.login_frame, width=40, font=('Arial', 12))
        self.code_entry.pack(pady=10)
        self.code_entry.focus()
        
        # Pre-fill if there's a saved code (even if auto-login failed)
        saved_code = self.config.get('saved_volunteer_code', '')
        if saved_code:
            self.code_entry.insert(0, saved_code)
        
        ttk.Button(self.login_frame, text="Start Recording Session", 
                  command=self._on_login).pack(pady=20)
        
        # Status label
        self.status_label = ttk.Label(self.login_frame, text="", foreground='red')
        self.status_label.pack()
        
    def _on_login(self):
        code = self.code_entry.get().strip()
        if not code:
            self.status_label.config(text="Please enter a code")
            return
            
        try:
            # Decode volunteer credentials
            creds = self._decode_volunteer_code(code)
            self.token = creds['t']
            self.start_idx = creds['s']
            self.count = creds['c']
            self.volunteer_name = creds['v']
            self.volunteer_code = code
            
            # Validate data file exists
            if not os.path.exists(DATA_FILE):
                messagebox.showerror("Error", f"Data file not found: {DATA_FILE}")
                return
                
            # Initialize managers
            self.data_manager = DataManager(DATA_FILE)
            self.assigned_rows = self.data_manager.get_assigned_indices(
                self.start_idx, self.count
            )
            
            if not self.assigned_rows:
                messagebox.showerror("Error", "No rows assigned to this code")
                return
                
            # Initialize progress and logging
            self.progress = ProgressManager(code)
            self.gist_logger = GistLogger(
                self.config.get('gist_id'), 
                self.token, 
                self.volunteer_name
            )
            
            # Resume from where they left off
            self.current_pos = self.progress.data['current_index']
            if self.current_pos >= len(self.assigned_rows):
                self.current_pos = 0
            
            # SAVE THE CODE for future auto-login
            self.config['saved_volunteer_code'] = code
            self._save_config()
                
            # Switch to main UI
            self.login_frame.destroy()
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
        
        ttk.Label(header, text=f"Volunteer: {self.volunteer_name}", 
                 font=('Arial', 12, 'bold')).pack(side='left')
        
        # Logout button (to switch volunteers)
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
        """Clear saved code and return to login screen"""
        if messagebox.askyesno("Switch User", "Are you sure you want to switch to a different volunteer?"):
            self.config['saved_volunteer_code'] = ''
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
            self.assigned_rows = []
            self.current_pos = 0
            
            self._build_login_ui()
        
    def _update_display(self):
        if not self.assigned_rows or self.current_pos >= len(self.assigned_rows):
            return
            
        row_data = self.assigned_rows[self.current_pos]
        
        # Update progress
        total = len(self.assigned_rows)
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
            text=f"Global ID: {global_idx} | "
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
            # Save file
            row_data = self.assigned_rows[self.current_pos]
            filename = f"row_{row_data['global_idx']}.wav"
            filepath = os.path.join(RECORDINGS_DIR, self.volunteer_code, filename)
            
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
            
        row_data = self.assigned_rows[self.current_pos]
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
        if self.current_pos < len(self.assigned_rows) - 1:
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
        total = len(self.assigned_rows)
        
        log_data = {
            'volunteer_name': self.volunteer_name,
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
        zip_name = f"submission_{self.volunteer_name}_{timestamp}.zip"
        zip_path = os.path.join(EXPORTS_DIR, zip_name)
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Add recordings
            for row_idx, filepath in self.progress.data['recordings'].items():
                if os.path.exists(filepath):
                    arcname = os.path.basename(filepath)
                    zf.write(filepath, arcname)
                    
            # Add metadata
            metadata = {
                'volunteer_name': self.volunteer_name,
                'volunteer_code_hash': hashlib.sha256(self.volunteer_code.encode()).hexdigest()[:16],
                'export_date': timestamp,
                'rows_completed': len(self.progress.data['completed_rows']),
                'assignments': [
                    {
                        'global_idx': r['global_idx'],
                        'id': r['id'],
                        'text': r['text'],
                        'audio_file': os.path.basename(
                            self.progress.data['recordings'].get(str(r['global_idx']), '')
                        )
                    }
                    for r in self.assigned_rows
                    if self.progress.is_complete(r['global_idx'])
                ]
            }
            zf.writestr('metadata.json', json.dumps(metadata, indent=2))
            
        messagebox.showinfo("Export Complete", 
                          f"Created: {zip_path}\n\nPlease send this file to your project manager.")
                          
    def _on_close(self):
        if self.gist_logger:
            self._update_gist_log()
            self.gist_logger.stop()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = RecorderApp(root)
    root.mainloop()
