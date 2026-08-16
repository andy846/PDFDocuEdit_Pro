#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PDF Letterhead Template Management System
A desktop application developed with PyQt5 for managing PDF letterhead templates,
providing version control, secure storage, and report export functionality.
"""

import sys
import os
import json
import shutil
import hashlib
import datetime
import uuid
import csv
import json # Added for config file handling
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any

# We'll use a simple file-based locking mechanism instead of fcntl
import tempfile
import contextlib

class FileLock:
    """Simple cross-platform file lock"""
    def __init__(self, file_path):
        self.file_path = file_path
        self.lock_path = f"{file_path}.lock"
        self.lock_file = None
    
    def acquire(self):
        try:
            # Try to create the lock file - will fail if it already exists
            self.lock_file = open(self.lock_path, 'x')
            return True
        except FileExistsError:
            return False
    
    def release(self):
        if self.lock_file:
            self.lock_file.close()
            try:
                os.remove(self.lock_path)
            except OSError:
                pass  # Lock file already gone

@contextlib.contextmanager
def file_lock(file_path):
    """Context manager for file locking"""
    lock = FileLock(file_path)
    # Try to acquire the lock with exponential backoff
    for i in range(10):  # Try 10 times
        if lock.acquire():
            try:
                yield
            finally:
                lock.release()
            return
        import time
        time.sleep(0.1 * (2 ** i))  # Exponential backoff
    raise IOError(f"Could not acquire lock for {file_path}")

import fitz  # PyMuPDF
from core.resources import resource_path
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QPushButton, QTableWidget, 
                             QTableWidgetItem, QFileDialog, QMessageBox,
                             QInputDialog, QComboBox, QTabWidget, QLineEdit,
                             QSpinBox, QDoubleSpinBox, QTextEdit, QGroupBox,
                             QRadioButton, QCheckBox, QSlider, QScrollArea,
                             QSplitter, QStatusBar, QMenu, QToolBar,
                              QHeaderView, QAbstractItemView, QDialog, QSizePolicy,
                              QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator,
                              QFileDialog) # Added QFileDialog
from PyQt6.QtGui import (QAction, QIcon, QPixmap, QImage, QPainter, QColor, QFont,
                         QCursor, QDesktopServices, QPalette)
from PyQt6.QtCore import (Qt, QSize, QRect, QUrl, QThread, pyqtSignal,
                          QModelIndex, QTimer, QDateTime, QPoint, QMimeData)
from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
from jinja2 import Environment, FileSystemLoader, select_autoescape


class PDFValidator:
    """PDF file validation class"""
    
    @staticmethod
    def validate_pdf(file_path: str) -> bool:
        """Validate if the file is a valid PDF"""
        try:
            with open(file_path, 'rb') as f:
                header = f.read(4)
                return header == b'%PDF'
        except Exception:
            return False

    @staticmethod
    def generate_hash(file_path: str) -> str:
        """Generate SHA-256 hash for PDF file"""
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            while chunk := f.read(8192):
                sha256.update(chunk)
        return sha256.hexdigest()
    
    @staticmethod
    def validate_hash(file_path: str, stored_hash: str) -> bool:
        """Validate if PDF file hash matches stored hash"""
        return PDFValidator.generate_hash(file_path) == stored_hash


class VersionManager:
    """Version control management class with Job support"""
    
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self._ensure_base_dir()
    
    def _ensure_base_dir(self) -> None:
        """Ensure base directory structure exists"""
        if not os.path.exists(self.base_dir):
            os.makedirs(self.base_dir)
        
        # Create backup directory (outside job folders)
        backup_dir = os.path.join(self.base_dir, "_backups") # Use underscore to avoid conflicts
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)

    # --- Job Management ---

    def get_job_dir(self, job_name: str) -> str:
        """Get job directory path"""
        # Basic sanitization - replace potentially problematic characters
        safe_job_name = "".join(c if c.isalnum() or c in (' ', '_', '-') else '_' for c in job_name).strip()
        if not safe_job_name:
            raise ValueError("Job name cannot be empty or contain only invalid characters.")
        return os.path.join(self.base_dir, safe_job_name)

    def job_exists(self, job_name: str) -> bool:
        """Check if job exists"""
        return os.path.exists(self.get_job_dir(job_name))

    def create_job(self, job_name: str) -> None:
        """Create a new job directory"""
        job_dir = self.get_job_dir(job_name)
        if not os.path.exists(job_dir):
            os.makedirs(job_dir)
            # Optional: Initialize job metadata if needed later
            # job_metadata_path = os.path.join(job_dir, "job_metadata.json")
            # with open(job_metadata_path, 'w') as f:
            #     json.dump({"name": job_name, "created_at": datetime.datetime.now().isoformat()}, f, indent=2)
        else:
            raise ValueError(f"Job '{job_name}' already exists.")

    def get_all_jobs(self) -> List[str]:
        """Get a list of all job names"""
        jobs = []
        for item in os.listdir(self.base_dir):
            # Exclude special directories like backups
            if item.startswith("_"): 
                continue
            dir_path = os.path.join(self.base_dir, item)
            if os.path.isdir(dir_path):
                jobs.append(item) # Use directory name as job name for now
        return sorted(jobs)

    def delete_job(self, job_name: str) -> None:
        """Delete an entire job and all its templates"""
        job_dir = self.get_job_dir(job_name)
        if os.path.exists(job_dir):
            shutil.rmtree(job_dir)
        else:
            raise ValueError(f"Job '{job_name}' not found.")

    # --- Template Management (within a Job) ---

    def get_template_dir(self, job_name: str, template_name: str) -> str:
        """Get template directory path within a job"""
        safe_template_name = "".join(c if c.isalnum() or c in (' ', '_', '-') else '_' for c in template_name).strip()
        if not safe_template_name:
             raise ValueError("Template name cannot be empty or contain only invalid characters.")
        return os.path.join(self.get_job_dir(job_name), safe_template_name)

    def get_template_metadata_path(self, job_name: str, template_name: str) -> str:
        """Get template metadata file path"""
        return os.path.join(self.get_template_dir(job_name, template_name), "metadata.json")

    def template_exists(self, job_name: str, template_name: str) -> bool:
        """Check if template exists within a job"""
        return os.path.exists(self.get_template_dir(job_name, template_name))

    def get_version_path(self, job_name: str, template_name: str, version: str) -> str:
        """Get specific version PDF file path"""
        return os.path.join(self.get_template_dir(job_name, template_name), f"v{version}.pdf")

    def create_template(self, job_name: str, template_name: str, product_name: str = "", part_id: str = "", 
                    start_date: str = "", end_date: str = "") -> None:
        """Create new template directory within a job"""
        if not self.job_exists(job_name):
            raise ValueError(f"Job '{job_name}' does not exist.")
        template_dir = self.get_template_dir(job_name, template_name)
        if not os.path.exists(template_dir):
            os.makedirs(template_dir)
            # Initialize metadata file
            metadata = {
                "job": job_name, # Store job context
                "name": template_name,
                "created_at": datetime.datetime.now().isoformat(),
                "active_version": None,
                "product_name": product_name,  # Add new field
                "part_id": part_id,            # Add new field
                "start_date": start_date,      # Add new date field
                "end_date": end_date,          # Add new date field
                "versions": []
            }
            self._save_template_metadata(job_name, template_name, metadata)
        else:
            raise ValueError(f"Template '{template_name}' already exists in job '{job_name}'.")

    def _save_template_metadata(self, job_name: str, template_name: str, metadata: Dict) -> None:
        """Save template metadata (using atomic operation)"""
        metadata_path = self.get_template_metadata_path(job_name, template_name)
        tmp_path = f"{metadata_path}.tmp"
        
        # Write to temporary file
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        
        # Atomic replace - this is an atomic operation on most file systems
        os.replace(tmp_path, metadata_path)
    
    def _load_template_metadata(self, job_name: str, template_name: str) -> Dict:
        """Load template metadata"""
        metadata_path = self.get_template_metadata_path(job_name, template_name)
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                 print(f"Warning: Corrupted metadata file at {metadata_path}")
                 # Return a default structure or raise a specific error
                 return {"job": job_name, "name": template_name, "versions": []} 
        return {} # Should not happen if create_template was called

    def add_version(self, job_name: str, template_name: str, pdf_path: str, version: str, summary: str = "", 
                product_name: str = "", part_id: str = "", start_date: str = "", end_date: str = "") -> None:
        """Add new version to a template within a job"""
        if not self.template_exists(job_name, template_name):
            self.create_template(job_name, template_name, product_name, part_id, start_date, end_date)
        
        # Calculate hash
        file_hash = PDFValidator.generate_hash(pdf_path)
        
        # Load metadata
        metadata = self._load_template_metadata(job_name, template_name)
        
        # Check version conflict
        for v in metadata.get("versions", []):
            if v["version"] == version:
                raise ValueError(f"Version {version} already exists for template '{template_name}' in job '{job_name}'.")
        
        # Copy PDF file to template directory
        target_path = self.get_version_path(job_name, template_name, version)
        shutil.copy2(pdf_path, target_path)
        
        # Update metadata
        # Ensure job name is stored if missing (for older metadata)
        if "job" not in metadata:
            metadata["job"] = job_name
            
        # 如果沒有提供新值，但元數據中有，則使用元數據中的值
        if not product_name and "product_name" in metadata and metadata["product_name"]:
            product_name = metadata["product_name"]
        # 更新模板級別的產品名稱
        if product_name:
            metadata["product_name"] = product_name
            
        if not part_id and "part_id" in metadata and metadata["part_id"]:
            part_id = metadata["part_id"]
        # 更新模板級別的部件ID
        if part_id:
            metadata["part_id"] = part_id
            
        # 處理日期欄位
        if not start_date and "start_date" in metadata and metadata["start_date"]:
            start_date = metadata["start_date"]
        if start_date:
            metadata["start_date"] = start_date
            
        if not end_date and "end_date" in metadata and metadata["end_date"]:
            end_date = metadata["end_date"]
        if end_date:
            metadata["end_date"] = end_date
        
        # Update new version info
        new_version = {
            "version": version,
            "date": datetime.datetime.now().isoformat(),
            "summary": summary,
            "file_hash": file_hash,
            "file_path": os.path.basename(target_path),
            "product_name": product_name,  # Add to version level too
            "part_id": part_id,            # Add to version level too
            "start_date": start_date,      # Add new date field
            "end_date": end_date           # Add new date field
        }
        
        metadata["versions"].append(new_version)
        metadata["active_version"] = version
        
        # Save metadata
        self._save_template_metadata(job_name, template_name, metadata)

    def get_templates_for_job(self, job_name: str) -> List[Dict]:
        """Get all template information for a specific job"""
        job_dir = self.get_job_dir(job_name)
        if not os.path.exists(job_dir):
            return []

        templates = []
        for item in os.listdir(job_dir):
            template_dir_path = os.path.join(job_dir, item)
            if os.path.isdir(template_dir_path):
                metadata_path = os.path.join(template_dir_path, "metadata.json")
                if os.path.exists(metadata_path):
                    try:
                        with open(metadata_path, 'r', encoding='utf-8') as f:
                            metadata = json.load(f)
                            templates.append({
                                "job": job_name, # Add job context
                                "name": metadata.get("name", item),
                                "active_version": metadata.get("active_version"),
                                "versions_count": len(metadata.get("versions", [])),
                                "created_at": metadata.get("created_at"),
                                "product_name": metadata.get("product_name", ""),  # Add new field
                                "part_id": metadata.get("part_id", ""),           # Add new field
                                "start_date": metadata.get("start_date", ""),     # Add new date field
                                "end_date": metadata.get("end_date", "")          # Add new date field
                            })
                    except json.JSONDecodeError:
                        print(f"Warning: Could not decode metadata for template '{item}' in job '{job_name}'. Skipping.")
                        continue # Skip corrupted metadata
        return sorted(templates, key=lambda x: x['name']) # Sort templates alphabetically by name

    def get_template_versions(self, job_name: str, template_name: str) -> List[Dict]:
        """Get all versions of a template within a job"""
        metadata = self._load_template_metadata(job_name, template_name)
        return metadata.get("versions", [])

    def get_active_version(self, job_name: str, template_name: str) -> Optional[Dict]:
        """Get current active version information for a template within a job"""
        metadata = self._load_template_metadata(job_name, template_name)
        active_version = metadata.get("active_version")
        
        if not active_version:
            return None
            
        for version_info in metadata.get("versions", []):
            if version_info["version"] == active_version:
                return version_info
        
        return None # Active version points to a non-existent version

    def set_active_version(self, job_name: str, template_name: str, version: str) -> None:
        """Set active version for a template within a job"""
        metadata = self._load_template_metadata(job_name, template_name)
        
        # Verify version exists
        version_exists = any(v["version"] == version for v in metadata.get("versions", []))
                
        if not version_exists:
            raise ValueError(f"Version {version} does not exist for template '{template_name}' in job '{job_name}'.")
        
        metadata["active_version"] = version
        self._save_template_metadata(job_name, template_name, metadata)

    def delete_template(self, job_name: str, template_name: str) -> None:
        """Delete a template within a job"""
        template_dir = self.get_template_dir(job_name, template_name)
        if os.path.exists(template_dir):
            shutil.rmtree(template_dir)
        else:
             raise ValueError(f"Template '{template_name}' not found in job '{job_name}'.")

    def verify_job_integrity(self, job_name: str) -> Dict[str, Dict[str, bool]]:
        """Verify integrity of all versions of all templates within a job"""
        job_results = {}
        templates = self.get_templates_for_job(job_name)
        
        for template in templates:
            template_name = template["name"]
            template_results = {}
            metadata = self._load_template_metadata(job_name, template_name)
            
            for version_info in metadata.get("versions", []):
                version_str = version_info["version"]
                file_path = self.get_version_path(job_name, template_name, version_str)
                stored_hash = version_info.get("file_hash", "") # Handle missing hash gracefully
                
                # Check if file exists and verify hash
                if os.path.exists(file_path) and stored_hash:
                    template_results[version_str] = PDFValidator.validate_hash(file_path, stored_hash)
                else:
                    template_results[version_str] = False # File missing or hash missing
            
            job_results[template_name] = template_results
            
        return job_results

    def verify_all_integrity(self) -> Dict[str, Dict[str, Dict[str, bool]]]:
         """Verify integrity of all templates across all jobs"""
         all_results = {}
         for job_name in self.get_all_jobs():
             all_results[job_name] = self.verify_job_integrity(job_name)
         return all_results

    def create_backup(self, backup_path: str = None) -> str:
        """Create system backup of all jobs and templates"""
        if backup_path is None:
            backup_dir = os.path.join(self.base_dir, "_backups")
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = os.path.join(backup_dir, f"backup_{timestamp}.zip")
        else:
            # Ensure the directory exists
            backup_dir = os.path.dirname(backup_path)
            if not os.path.exists(backup_dir):
                os.makedirs(backup_dir)

            # Add .zip extension if not present
            if not backup_path.lower().endswith('.zip'):
                backup_path += '.zip'
        
        # Create temporary directory for files to be backed up
        temp_dir = tempfile.mkdtemp()
        
        try:
            # Copy all job directories to temp directory, excluding _backups
            for item in os.listdir(self.base_dir):
                if not item.startswith("_"): # Exclude special dirs
                    src_path = os.path.join(self.base_dir, item)
                    if os.path.isdir(src_path):
                        dst_path = os.path.join(temp_dir, item)
                        shutil.copytree(src_path, dst_path)
            
            # Create zip from the temp directory (containing job folders)
            shutil.make_archive(
                backup_path.replace(".zip", ""),
                'zip',
                temp_dir
            )
            
            return backup_path
            
        finally:
            # Clean up temporary directory
            shutil.rmtree(temp_dir, ignore_errors=True)

    def update_template_info(self, job_name: str, template_name: str, 
                        product_name: str = None, part_id: str = None,
                        start_date: str = None, end_date: str = None) -> None:
        """Update template information"""
        if not self.template_exists(job_name, template_name):
            raise ValueError(f"Template '{template_name}' does not exist in job '{job_name}'.")
        
        # Load metadata
        metadata = self._load_template_metadata(job_name, template_name)
        
        # Update fields if provided
        if product_name is not None:
            metadata["product_name"] = product_name
        
        if part_id is not None:
            metadata["part_id"] = part_id
            
        if start_date is not None:
            metadata["start_date"] = start_date
            
        if end_date is not None:
            metadata["end_date"] = end_date
        
        # Save updated metadata
        self._save_template_metadata(job_name, template_name, metadata)


class ReportGenerator:
    """Report generator class"""
    
    def __init__(self, templates_dir: str = "report_templates"):
        self.templates_dir = templates_dir
        self.jinja_env = Environment(
            loader=FileSystemLoader(templates_dir),
            autoescape=select_autoescape(['html', 'xml'])
        )
    
    def generate_text_report(self, template_name: str, versions: List[Dict], output_path: str) -> None:
        """Generate text format report"""
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(f"Template Name: {template_name}\n")
            f.write(f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("="*50 + "\n\n")
            
            for version in versions:
                f.write(f"Version: {version['version']}\n")
                f.write(f"Date: {version['date']}\n")
                f.write(f"Product Name: {version.get('product_name', '')}\n")
                f.write(f"PART ID: {version.get('part_id', '')}\n")
                f.write(f"Valid Period: {version.get('start_date', '')} ~ {version.get('end_date', '')}\n")  # Added new fields
                f.write(f"Change Summary: {version['summary']}\n")
                f.write(f"File Hash: {version['file_hash']}\n")
                f.write("-"*50 + "\n\n")

    def generate_csv_report(self, template_name: str, versions: List[Dict], output_path: str) -> None:
        """Generate CSV format report"""
        with open(output_path, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            # Write header row - UPDATED WITH NEW FIELDS
            writer.writerow([
                "Template Name", "Version", "Date", "Product Name", "PART ID", 
                "Start Date", "End Date", "Change Summary", "File Hash"
            ])
            
            # Write data rows
            for version in versions:
                date_str = version['date']
                # Try to convert ISO format time to a more friendly format
                try:
                    dt = datetime.datetime.fromisoformat(date_str)
                    date_str = dt.strftime('%Y-%m-%d %H:%M:%S')
                except ValueError:
                    pass
                
                writer.writerow([
                    template_name,
                    version['version'],
                    date_str,
                    version.get('product_name', ''),
                    version.get('part_id', ''),
                    version.get('start_date', ''),   # Add new field
                    version.get('end_date', ''),     # Add new field
                    version['summary'],
                    version['file_hash']
                ])

    def generate_pdf_report(self, template_name: str, versions: List[Dict], output_path: str) -> None:
        """Generate PDF format report (simple implementation)"""
        # Create a simple PDF document
        doc = fitz.open()
        page = doc.new_page()
        
        # Set title - Use standard font names instead of "helv-bold"
        text = f"Template '{template_name}' Version History Report"
        page.insert_text((50, 50), text, fontsize=16, fontname="helvetica-bold")
        
        y_pos = 100
        for version in versions:
            # Try to convert ISO format time to a more friendly format
            date_str = version['date']
            try:
                dt = datetime.datetime.fromisoformat(date_str)
                date_str = dt.strftime('%Y-%m-%d %H:%M:%S')
            except ValueError:
                pass
            
            # Use "helvetica" instead of "helv" for font names
            page.insert_text((50, y_pos), f"Version: {version['version']}", fontsize=12)
            page.insert_text((50, y_pos + 20), f"Date: {date_str}", fontsize=12)
            page.insert_text((50, y_pos + 40), f"Product Name: {version.get('product_name', '')}", fontsize=12)
            page.insert_text((50, y_pos + 60), f"PART ID: {version.get('part_id', '')}", fontsize=12)
            page.insert_text((50, y_pos + 80), f"Start Date: {version.get('start_date', '')}", fontsize=12)
            page.insert_text((50, y_pos + 100), f"End Date: {version.get('end_date', '')}", fontsize=12)
            page.insert_text((50, y_pos + 120), f"Change Summary: {version['summary']}", fontsize=12)
            
            # Increase vertical spacing
            y_pos += 160  # Increased spacing to accommodate new fields
            
            # If page space is insufficient, create a new page
            if y_pos > 750:
                page = doc.new_page()
                y_pos = 50
        
        # Save document
        doc.save(output_path)
        doc.close()

    # --- Job Level Reports ---

    def generate_job_text_report(self, job_name: str, job_data: List[Dict], output_path: str) -> None:
        """Generate text format report for an entire job"""
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(f"Job Report: {job_name}\n")
            f.write(f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("="*70 + "\n\n")

            for template_data in job_data:
                template_name = template_data["name"]
                versions = template_data["versions"]
                f.write(f"--- Template: {template_name} ---\n")
                f.write(f"Product Name: {template_data.get('product_name', '')}\n")
                f.write(f"PART ID: {template_data.get('part_id', '')}\n")
                f.write(f"Valid Period: {template_data.get('start_date', '')} ~ {template_data.get('end_date', '')}\n")
                f.write(f"Active Version: {template_data.get('active_version', 'N/A')}\n")
                f.write(f"Total Versions: {len(versions)}\n\n")

                if not versions:
                    f.write("  (No versions found)\n")
                else:
                    for version in versions:
                        f.write(f"  Version: {version['version']}\n")
                        f.write(f"  Date: {version['date']}\n")
                        # Version-specific details (if they differ from template level)
                        f.write(f"  Version Product Name: {version.get('product_name', '')}\n")
                        f.write(f"  Version PART ID: {version.get('part_id', '')}\n")
                        f.write(f"  Version Valid Period: {version.get('start_date', '')} ~ {version.get('end_date', '')}\n")
                        f.write(f"  Change Summary: {version['summary']}\n")
                        f.write(f"  File Hash: {version['file_hash']}\n")
                        f.write("  "+"-"*50 + "\n")
                f.write("\n" + "="*70 + "\n\n")

    def generate_job_csv_report(self, job_name: str, job_data: List[Dict], output_path: str) -> None:
        """Generate CSV format report for an entire job"""
        with open(output_path, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            # Write header row - Include Job Name
            writer.writerow([
                "Job Name", "Template Name", "Template Product Name", "Template PART ID", 
                "Template Start Date", "Template End Date", "Active Version",
                "Version", "Version Date", "Version Product Name", "Version PART ID",
                "Version Start Date", "Version End Date", "Change Summary", "File Hash"
            ])

            # Write data rows
            for template_data in job_data:
                template_name = template_data["name"]
                versions = template_data["versions"]
                
                if not versions: # Write template info even if no versions
                     writer.writerow([
                        job_name,
                        template_name,
                        template_data.get('product_name', ''),
                        template_data.get('part_id', ''),
                        template_data.get('start_date', ''),
                        template_data.get('end_date', ''),
                        template_data.get('active_version', 'N/A'),
                        "N/A", "N/A", "N/A", "N/A", "N/A", "N/A", "No versions", "N/A"
                    ])
                else:
                    for version in versions:
                        date_str = version['date']
                        try:
                            dt = datetime.datetime.fromisoformat(date_str)
                            date_str = dt.strftime('%Y-%m-%d %H:%M:%S')
                        except ValueError:
                            pass
                        
                        writer.writerow([
                            job_name,
                            template_name,
                            template_data.get('product_name', ''),
                            template_data.get('part_id', ''),
                            template_data.get('start_date', ''),
                            template_data.get('end_date', ''),
                            template_data.get('active_version', 'N/A'),
                            version['version'],
                            date_str,
                            version.get('product_name', ''), # Version specific
                            version.get('part_id', ''),      # Version specific
                            version.get('start_date', ''),   # Version specific
                            version.get('end_date', ''),     # Version specific
                            version['summary'],
                            version['file_hash']
                        ])

    def generate_job_pdf_report(self, job_name: str, job_data: List[Dict], output_path: str) -> None:
        """Generate PDF format report for an entire job (simple implementation)"""
        doc = fitz.open()
        page = doc.new_page()
        y_pos = 50

        # Job Title
        page.insert_text((50, y_pos), f"Job Report: {job_name}", fontsize=18)
        y_pos += 30
        page.insert_text((50, y_pos), f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", fontsize=10)
        y_pos += 40

        for template_data in job_data:
            template_name = template_data["name"]
            versions = template_data["versions"]

            # Check space before starting template section
            if y_pos > 700: # Need space for template header + at least one version
                page = doc.new_page()
                y_pos = 50

            # Draw a separator line - FIXED THIS LINE
            # Use draw_line instead of insert_line
            page.draw_line((50, y_pos - 5), (page.rect.width - 50, y_pos - 5), color=(0.5, 0.5, 0.5))
            
            page.insert_text((50, y_pos + 15), f"Template: {template_name}", fontsize=14)
            y_pos += 35
            page.insert_text((60, y_pos), f"Product: {template_data.get('product_name', 'N/A')}, PART ID: {template_data.get('part_id', 'N/A')}", fontsize=10)
            y_pos += 15
            page.insert_text((60, y_pos), f"Valid: {template_data.get('start_date', 'N/A')} ~ {template_data.get('end_date', 'N/A')}", fontsize=10)
            y_pos += 15
            page.insert_text((60, y_pos), f"Active Version: {template_data.get('active_version', 'N/A')}", fontsize=10)
            y_pos += 25

            if not versions:
                page.insert_text((70, y_pos), "(No versions found)", fontsize=10)
                y_pos += 20
            else:
                for version in versions:
                    # Check space for version details
                    if y_pos > 750: 
                        page = doc.new_page()
                        y_pos = 50
                        page.insert_text((50, y_pos), f"Job Report: {job_name} (cont.)", fontsize=18)
                        y_pos += 30
                        page.insert_text((50, y_pos), f"Template: {template_name} (cont.)", fontsize=14)
                        y_pos += 30

                    date_str = version['date']
                    try:
                        dt = datetime.datetime.fromisoformat(date_str)
                        date_str = dt.strftime('%Y-%m-%d %H:%M:%S')
                    except ValueError:
                        pass
                    
                    page.insert_text((70, y_pos), f"Version: {version['version']}", fontsize=11)
                    y_pos += 15
                    page.insert_text((80, y_pos), f"Date: {date_str}", fontsize=10)
                    y_pos += 15
                    page.insert_text((80, y_pos), f"Summary: {version['summary']}", fontsize=10)
                    y_pos += 15
                    # Add version-specific details if needed
                    page.insert_text((80, y_pos), f"Version Product: {version.get('product_name', 'N/A')}, PART ID: {version.get('part_id', 'N/A')}", fontsize=9)
                    y_pos += 12
                    page.insert_text((80, y_pos), f"Version Valid: {version.get('start_date', 'N/A')} ~ {version.get('end_date', 'N/A')}", fontsize=9)
                    y_pos += 20 # Space before next version

            y_pos += 15 # Space after template section

        # Save document
        doc.save(output_path)
        doc.close()


class EditTemplateDialog(QDialog):
    """Dialog for editing template information"""
    
    def __init__(self, template_info, parent=None):
        super().__init__(parent)
        self.template_info = template_info
        self.setWindowTitle(f"Edit Template: {template_info['name']}")
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)
        self.initUI()
    
    def initUI(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        
        # Template information section
        info_group = QGroupBox("Template Information")
        info_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(20, 30, 20, 20)
        info_layout.setSpacing(15)
        
        # Template name (display only)
        name_layout = QHBoxLayout()
        name_label = QLabel("Template Name:")
        name_label.setMinimumWidth(180)
        # name_label.setStyleSheet("font-size: 16px;") # Removed font size
        self.name_label = QLabel(self.template_info.get("name", ""))
        self.name_label.setStyleSheet("font-weight: bold;") # Removed font size
        name_layout.addWidget(name_label)
        name_layout.addWidget(self.name_label)
        info_layout.addLayout(name_layout)
        
        # Job name (display only)
        job_layout = QHBoxLayout()
        job_label = QLabel("Job:")
        job_label.setMinimumWidth(180)
        # job_label.setStyleSheet("font-size: 16px;") # Removed font size
        self.job_label = QLabel(self.template_info.get("job", ""))
        self.job_label.setStyleSheet("font-weight: bold;") # Removed font size
        job_layout.addWidget(job_label)
        job_layout.addWidget(self.job_label)
        info_layout.addLayout(job_layout)
        
        # Editable fields
        # Product name
        product_layout = QHBoxLayout()
        product_label = QLabel("Product Name:")
        product_label.setMinimumWidth(180)
        # product_label.setStyleSheet("font-size: 16px;") # Removed font size
        self.product_edit = QLineEdit(self.template_info.get("product_name", ""))
        self.product_edit.setMinimumHeight(30)
        # self.product_edit.setStyleSheet("font-size: 16px;") # Removed font size
        product_layout.addWidget(product_label)
        product_layout.addWidget(self.product_edit)
        info_layout.addLayout(product_layout)
        
        # Part ID
        part_id_layout = QHBoxLayout()
        part_id_label = QLabel("PART ID:")
        part_id_label.setMinimumWidth(180)
        # part_id_label.setStyleSheet("font-size: 16px;") # Removed font size
        self.part_id_edit = QLineEdit(self.template_info.get("part_id", ""))
        self.part_id_edit.setMinimumHeight(30)
        # self.part_id_edit.setStyleSheet("font-size: 16px;") # Removed font size
        part_id_layout.addWidget(part_id_label)
        part_id_layout.addWidget(self.part_id_edit)
        info_layout.addLayout(part_id_layout)
        
        # Start Date
        start_date_layout = QHBoxLayout()
        start_date_label = QLabel("Start Date:")
        start_date_label.setMinimumWidth(180)
        # start_date_label.setStyleSheet("font-size: 16px;") # Removed font size
        self.start_date_edit = QLineEdit(self.template_info.get("start_date", ""))
        self.start_date_edit.setPlaceholderText("YYYY-MM-DD")
        self.start_date_edit.setMinimumHeight(30)
        # self.start_date_edit.setStyleSheet("font-size: 16px;") # Removed font size
        start_date_layout.addWidget(start_date_label)
        start_date_layout.addWidget(self.start_date_edit)
        info_layout.addLayout(start_date_layout)
        
        # End Date
        end_date_layout = QHBoxLayout()
        end_date_label = QLabel("End Date:")
        end_date_label.setMinimumWidth(180)
        # end_date_label.setStyleSheet("font-size: 16px;") # Removed font size
        self.end_date_edit = QLineEdit(self.template_info.get("end_date", ""))
        self.end_date_edit.setPlaceholderText("YYYY-MM-DD")
        self.end_date_edit.setMinimumHeight(30)
        # self.end_date_edit.setStyleSheet("font-size: 16px;") # Removed font size
        end_date_layout.addWidget(end_date_label)
        end_date_layout.addWidget(self.end_date_edit)
        info_layout.addLayout(end_date_layout)
        
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)
        
        # Buttons section
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(20)
        
        self.cancel_button = QPushButton("Cancel")
        self.save_button = QPushButton("Save Changes")
        self.cancel_button.setMinimumHeight(30)
        self.save_button.setMinimumHeight(30)
        self.cancel_button.setMinimumWidth(200)
        self.save_button.setMinimumWidth(200)
        # self.cancel_button.setStyleSheet("font-size: 18px;") # Removed font size
        # self.save_button.setStyleSheet("font-size: 18px;") # Removed font size
        self.cancel_button.clicked.connect(self.reject)
        self.save_button.clicked.connect(self.accept)
        
        buttons_layout.addStretch()
        buttons_layout.addWidget(self.cancel_button)
        buttons_layout.addWidget(self.save_button)
        
        layout.addLayout(buttons_layout)
        self.setLayout(layout)
    
    def get_updated_data(self):
        """Get updated template data"""
        return {
            "product_name": self.product_edit.text(),
            "part_id": self.part_id_edit.text(),
            "start_date": self.start_date_edit.text(),
            "end_date": self.end_date_edit.text()
        }


class PDFPreviewWidget(QWidget):
    """PDF preview component"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.initUI()
        self.current_doc = None
        self.current_page = 0
        self.zoom_factor = 1.0
    
    def initUI(self):
        # Create layout
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(15)
        
        # Create control toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(15)
        
        # Create page navigation controls
        self.page_label = QLabel("Page: 0/0")
        self.page_label.setMinimumWidth(60)
        # self.page_label.setStyleSheet("font-size: 16px;") # Removed font size
        
        self.prev_button = QPushButton("<<")
        self.next_button = QPushButton(">>")
        self.prev_button.setMinimumWidth(100)
        self.next_button.setMinimumWidth(100)
        self.prev_button.setMinimumHeight(30)
        self.next_button.setMinimumHeight(30)
        # self.prev_button.setStyleSheet("font-size: 20px;") # Removed font size
        # self.next_button.setStyleSheet("font-size: 20px;") # Removed font size
        self.prev_button.clicked.connect(self.prev_page)
        self.next_button.clicked.connect(self.next_page)
        
        # Create zoom controls
        self.zoom_out_button = QPushButton("-")
        self.zoom_in_button = QPushButton("+")
        self.zoom_label = QLabel("100%")
        self.zoom_out_button.setMinimumWidth(100)
        self.zoom_in_button.setMinimumWidth(100)
        self.zoom_label.setMinimumWidth(60)
        self.zoom_out_button.setMinimumHeight(30)
        self.zoom_in_button.setMinimumHeight(30)
        # self.zoom_out_button.setStyleSheet("font-size: 20px;") # Removed font size
        # self.zoom_in_button.setStyleSheet("font-size: 20px;") # Removed font size
        # self.zoom_label.setStyleSheet("font-size: 20px;") # Removed font size
        self.zoom_out_button.clicked.connect(self.zoom_out) # Connects button click
        self.zoom_in_button.clicked.connect(self.zoom_in)   # Connects button click
        
        # Add controls to toolbar
        toolbar.addWidget(self.prev_button)
        toolbar.addWidget(self.page_label)
        toolbar.addWidget(self.next_button)
        toolbar.addStretch()
        toolbar.addWidget(self.zoom_out_button)
        toolbar.addWidget(self.zoom_label)
        toolbar.addWidget(self.zoom_in_button)
        
        # Create preview area - use standard A4 ratio ~1:1.414
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(720, 1018)  # Slightly larger than A4 at 72 DPI
        self.preview_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
        self.preview_label.setStyleSheet("background-color: #2D2D30; border: 1px solid #3F3F46;")
        
        # Create a scroll area for the preview
        self.scroll_area = QScrollArea() # Store scroll area reference
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.preview_label)
        self.scroll_area.setStyleSheet("border: none;")
        # Set focus policy for the scroll area to capture key events
        self.scroll_area.setFocusPolicy(Qt.FocusPolicy.StrongFocus) 
        
        # Add toolbar and preview area to main layout
        layout.addLayout(toolbar)
        layout.addWidget(self.scroll_area) # Use the stored reference
        
        self.setLayout(layout)
        # Set focus policy for the main widget to capture key events when scroll area doesn't have focus
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus) 
        
        # Disable buttons until PDF is loaded
        self.prev_button.setEnabled(False)
        self.next_button.setEnabled(False)
        self.zoom_out_button.setEnabled(False)
        self.zoom_in_button.setEnabled(False)
    
    def load_pdf(self, pdf_path):
        """Load PDF file"""
        try:
            # Close previous document
            if self.current_doc:
                self.current_doc.close()
            
            # Open new document
            self.current_doc = fitz.open(pdf_path)
            self.current_page = 0
            
            # Update page label
            self.page_label.setText(f"Page: 1/{self.current_doc.page_count}")
            
            # Enable buttons
            self.prev_button.setEnabled(True)
            self.next_button.setEnabled(True)
            self.zoom_out_button.setEnabled(True)
            self.zoom_in_button.setEnabled(True)
            
            # Display first page
            self.display_page()
            
            return True
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Cannot load PDF file: {e}")
            return False
    
    def display_page(self):
        """Display current page"""
        if not self.current_doc:
            return
        
        page = self.current_doc.load_page(self.current_page)
        zoom_matrix = fitz.Matrix(self.zoom_factor, self.zoom_factor)
        pixmap = page.get_pixmap(matrix=zoom_matrix)
        
        # Convert Pixmap to QImage
        img = QImage(pixmap.samples, pixmap.width, pixmap.height, 
                   pixmap.stride, QImage.Format_RGB888)
        
        # Display image
        self.preview_label.setPixmap(QPixmap.fromImage(img))
        
        # Update page label
        self.page_label.setText(f"Page: {self.current_page + 1}/{self.current_doc.page_count}")
    
    def prev_page(self):
        """Display previous page"""
        if self.current_doc and self.current_page > 0:
            self.current_page -= 1
            self.display_page()
    
    def next_page(self):
        """Display next page"""
        if self.current_doc and self.current_page < self.current_doc.page_count - 1:
            self.current_page += 1
            self.display_page()
    
    def zoom_in(self):
        """Zoom in"""
        if self.zoom_factor < 2.0:
            self.zoom_factor += 0.1
            self.zoom_label.setText(f"{int(self.zoom_factor * 100)}%")
            self.display_page()
    
    def zoom_out(self):
        """Zoom out"""
        # Adjusted minimum zoom slightly to avoid potential zero/negative zoom issues
        if self.zoom_factor > 0.2: 
            self.zoom_factor -= 0.1
            # Ensure zoom factor doesn't go too low
            self.zoom_factor = max(0.1, self.zoom_factor) 
            self.zoom_label.setText(f"{int(self.zoom_factor * 100)}%")
            self.display_page()

    # --- Event Handlers for Shortcuts ---

    def keyPressEvent(self, event):
        """Handle key press events for navigation"""
        if not self.current_doc: # Do nothing if no PDF is loaded
            super().keyPressEvent(event)
            return
            
        key = event.key()
        
        if key == Qt.Key.Key_Left:
            self.prev_page()
            event.accept() # Indicate event was handled
        elif key == Qt.Key.Key_Right:
            self.next_page()
            event.accept() # Indicate event was handled
        else:
            # Pass unhandled key events to the base class
            super().keyPressEvent(event) # Pass the event object

    def wheelEvent(self, event):
        """Handle mouse wheel events for zooming with Ctrl key"""
        if not self.current_doc: # Do nothing if no PDF is loaded
            super().wheelEvent(event)
            return

        # Check if Ctrl key is pressed
        modifiers = QApplication.keyboardModifiers()
        if modifiers == Qt.KeyboardModifier.ControlModifier:
            # Get scroll direction (positive for up/forward, negative for down/backward)
            delta = event.angleDelta().y() 
            
            if delta > 0: # Scroll up (zoom in)
                self.zoom_in()
                event.accept() # Indicate event was handled
            elif delta < 0: # Scroll down (zoom out)
                self.zoom_out()
                event.accept() # Indicate event was handled
            else:
                 # Pass unhandled wheel events (e.g., horizontal scroll) to the base class
                 super().wheelEvent(event)
        else:
            # If Ctrl is not pressed, let the default scroll behavior handle it (e.g., scrolling the page view)
            super().wheelEvent(event)


class ImportTemplateDialog(QDialog):
    """Import template dialog"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import Template")
        self.setMinimumWidth(800)
        self.setMinimumHeight(700)  # Increased height for new fields
        self.initUI()
        
        # Initialize variables
        self.pdf_path = ""
    
    def initUI(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        
        # File selection section
        file_group = QGroupBox("PDF File")
        file_group.setStyleSheet("QGroupBox { font-weight: bold; }") # Removed font size
        file_layout = QHBoxLayout()
        file_layout.setContentsMargins(20, 30, 20, 20)
        file_layout.setSpacing(15)
        
        self.file_path_edit = QLineEdit()
        self.file_path_edit.setReadOnly(True)
        self.file_path_edit.setMinimumHeight(30)
        # self.file_path_edit.setStyleSheet("font-size: 16px;") # Removed font size
        
        self.browse_button = QPushButton("Browse...")
        self.browse_button.setMinimumHeight(30)
        self.browse_button.setMinimumWidth(150)
        # self.browse_button.setStyleSheet("font-size: 16px;") # Removed font size
        self.browse_button.clicked.connect(self.browse_file)
        
        file_layout.addWidget(self.file_path_edit)
        file_layout.addWidget(self.browse_button)
        file_group.setLayout(file_layout)
        layout.addWidget(file_group)
        
        # Template information section
        info_group = QGroupBox("Template Information")
        info_group.setStyleSheet("QGroupBox { font-weight: bold; }") # Removed font size
        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(20, 30, 20, 20)
        info_layout.setSpacing(15)
        
        # Template name
        name_layout = QHBoxLayout()
        name_label = QLabel("Template Name:")
        name_label.setMinimumWidth(180)
        # name_label.setStyleSheet("font-size: 16px;") # Removed font size
        self.name_edit = QLineEdit()
        self.name_edit.setMinimumHeight(30)
        # self.name_edit.setStyleSheet("font-size: 16px;") # Removed font size
        name_layout.addWidget(name_label)
        name_layout.addWidget(self.name_edit)
        info_layout.addLayout(name_layout)
        
        # Product name
        product_layout = QHBoxLayout()
        product_label = QLabel("Product Name:")
        product_label.setMinimumWidth(180)
        # product_label.setStyleSheet("font-size: 16px;") # Removed font size
        self.product_edit = QLineEdit()
        self.product_edit.setMinimumHeight(30)
        # self.product_edit.setStyleSheet("font-size: 16px;") # Removed font size
        product_layout.addWidget(product_label)
        product_layout.addWidget(self.product_edit)
        info_layout.addLayout(product_layout)
        
        # Part ID
        part_id_layout = QHBoxLayout()
        part_id_label = QLabel("PART ID:")
        part_id_label.setMinimumWidth(180)
        # part_id_label.setStyleSheet("font-size: 16px;") # Removed font size
        self.part_id_edit = QLineEdit()
        self.part_id_edit.setMinimumHeight(30)
        # self.part_id_edit.setStyleSheet("font-size: 16px;") # Removed font size
        part_id_layout.addWidget(part_id_label)
        part_id_layout.addWidget(self.part_id_edit)
        info_layout.addLayout(part_id_layout)
        
        # Start Date - 新增欄位
        start_date_layout = QHBoxLayout()
        start_date_label = QLabel("Start Date:")
        start_date_label.setMinimumWidth(180)
        # start_date_label.setStyleSheet("font-size: 16px;") # Removed font size
        self.start_date_edit = QLineEdit()
        self.start_date_edit.setPlaceholderText("YYYY-MM-DD")
        self.start_date_edit.setMinimumHeight(30)
        # self.start_date_edit.setStyleSheet("font-size: 16px;") # Removed font size
        start_date_layout.addWidget(start_date_label)
        start_date_layout.addWidget(self.start_date_edit)
        info_layout.addLayout(start_date_layout)
        
        # End Date - 新增欄位
        end_date_layout = QHBoxLayout()
        end_date_label = QLabel("End Date:")
        end_date_label.setMinimumWidth(180)
        # end_date_label.setStyleSheet("font-size: 16px;") # Removed font size
        self.end_date_edit = QLineEdit()
        self.end_date_edit.setPlaceholderText("YYYY-MM-DD")
        self.end_date_edit.setMinimumHeight(30)
        # self.end_date_edit.setStyleSheet("font-size: 16px;") # Removed font size
        end_date_layout.addWidget(end_date_label)
        end_date_layout.addWidget(self.end_date_edit)
        info_layout.addLayout(end_date_layout)
        
        # Version number
        version_layout = QHBoxLayout()
        version_label = QLabel("Version:")
        version_label.setMinimumWidth(180)
        # version_label.setStyleSheet("font-size: 16px;") # Removed font size
        self.version_edit = QLineEdit("1.0")
        self.version_edit.setMinimumHeight(30)
        # self.version_edit.setStyleSheet("font-size: 16px;") # Removed font size
        version_layout.addWidget(version_label)
        version_layout.addWidget(self.version_edit)
        info_layout.addLayout(version_layout)
        
        # Change summary
        summary_layout = QHBoxLayout()
        summary_label = QLabel("Change Summary:")
        summary_label.setMinimumWidth(180)
        # summary_label.setStyleSheet("font-size: 16px;") # Removed font size
        self.summary_edit = QLineEdit("Initial version")
        self.summary_edit.setMinimumHeight(30)
        # self.summary_edit.setStyleSheet("font-size: 16px;") # Removed font size
        summary_layout.addWidget(summary_label)
        summary_layout.addWidget(self.summary_edit)
        info_layout.addLayout(summary_layout)
        
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)
        
        # Buttons section
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(20)
        
        self.cancel_button = QPushButton("Cancel")
        self.import_button = QPushButton("Import")
        self.cancel_button.setMinimumHeight(30)
        self.import_button.setMinimumHeight(30)
        self.cancel_button.setMinimumWidth(200)
        self.import_button.setMinimumWidth(200)
        # self.cancel_button.setStyleSheet("font-size: 18px;") # Removed font size
        # self.import_button.setStyleSheet("font-size: 18px;") # Removed font size
        self.cancel_button.clicked.connect(self.reject)
        self.import_button.clicked.connect(self.accept)
        self.import_button.setEnabled(False)  # Initially disabled
        
        buttons_layout.addStretch()
        buttons_layout.addWidget(self.cancel_button)
        buttons_layout.addWidget(self.import_button)
        
        layout.addLayout(buttons_layout)
        self.setLayout(layout)
    
    def browse_file(self):
        """Browse and select PDF file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select PDF File", "", "PDF Files (*.pdf)"
        )
        
        if file_path:
            # Validate if it's a valid PDF
            if PDFValidator.validate_pdf(file_path):
                self.pdf_path = file_path
                self.file_path_edit.setText(file_path)
                
                # Extract filename as default template name
                filename = os.path.basename(file_path)
                template_name = os.path.splitext(filename)[0]
                self.name_edit.setText(template_name)
                
                # Enable import button
                self.import_button.setEnabled(True)
            else:
                QMessageBox.warning(self, "Warning", "Selected file is not a valid PDF file.")
                self.pdf_path = ""
                self.file_path_edit.setText("")
                self.import_button.setEnabled(False)
    
    def get_import_data(self):
        """Get import data"""
        return {
            "pdf_path": self.pdf_path,
            "template_name": self.name_edit.text(),
            "version": self.version_edit.text(),
            "summary": self.summary_edit.text(),
            "product_name": self.product_edit.text(),
            "part_id": self.part_id_edit.text(),
            "start_date": self.start_date_edit.text(),
            "end_date": self.end_date_edit.text()
        }


class VersionHistoryDialog(QDialog):
    """Version history dialog"""
    
    version_activated = pyqtSignal(str)
    
    def __init__(self, template_name, versions, parent=None):
        super().__init__(parent)
        self.template_name = template_name
        self.versions = versions
        
        self.setWindowTitle(f"Version History - {template_name}")
        self.setMinimumSize(1600, 700)
        
        self.initUI()
        self.populate_versions()
    
    def initUI(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        
        # Version list
        self.version_table = QTableWidget()
        self.version_table.setColumnCount(8)  # Increased from 6 to 8 for new fields
        self.version_table.setHorizontalHeaderLabels([
            "Version", "Date", "Product Name", "PART ID", 
            "Start Date", "End Date", "Change Summary", "Status"
        ])
        self.version_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.version_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.version_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)  # Change Summary (index changed)
        self.version_table.doubleClicked.connect(self.on_version_double_clicked)
        self.version_table.setMinimumHeight(500)
        # self.version_table.setStyleSheet("font-size: 16px;") # Removed font size
        
        # Set column widths more appropriately
        self.version_table.setColumnWidth(0, 140)  # Version
        self.version_table.setColumnWidth(1, 200)  # Date
        self.version_table.setColumnWidth(2, 200)  # Product Name
        self.version_table.setColumnWidth(3, 150)  # PART ID
        self.version_table.setColumnWidth(4, 150)  # Start Date
        self.version_table.setColumnWidth(5, 150)  # End Date
        self.version_table.setColumnWidth(7, 160)  # Status (index changed)
        
        # Increase row height
        self.version_table.verticalHeader().setDefaultSectionSize(50)
        
        title_label = QLabel(f"Template: {self.template_name}")
        title_label.setStyleSheet("font-weight: bold;") # Removed font size
        layout.addWidget(title_label)
        layout.addWidget(self.version_table)
        
        # Buttons section
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(20)
        
        self.activate_button = QPushButton("Set as Current Version")
        self.close_button = QPushButton("Close")
        self.activate_button.setMinimumWidth(300)
        self.activate_button.setMinimumHeight(30)
        self.close_button.setMinimumWidth(200)
        self.close_button.setMinimumHeight(30)
        # self.activate_button.setStyleSheet("font-size: 18px;") # Removed font size
        # self.close_button.setStyleSheet("font-size: 18px;") # Removed font size
        
        self.activate_button.clicked.connect(self.activate_selected_version)
        self.close_button.clicked.connect(self.accept)
        
        buttons_layout.addStretch()
        buttons_layout.addWidget(self.activate_button)
        buttons_layout.addWidget(self.close_button)
        
        layout.addLayout(buttons_layout)
        self.setLayout(layout)

    def populate_versions(self):
        """Populate version list"""
        self.version_table.setRowCount(len(self.versions))
        
        # Find current active version
        active_version = None
        for v in self.versions:
            if v.get("active", False):
                active_version = v["version"]
                break
        
        for i, version in enumerate(self.versions):
            # Version number
            version_item = QTableWidgetItem(version["version"])
            self.version_table.setItem(i, 0, version_item)
            
            # Date
            date_str = version["date"]
            try:
                dt = datetime.datetime.fromisoformat(date_str)
                date_str = dt.strftime('%Y-%m-%d %H:%M:%S')
            except ValueError:
                pass
            date_item = QTableWidgetItem(date_str)
            self.version_table.setItem(i, 1, date_item)
            
            # Product Name
            product_name = version.get("product_name", "")
            product_item = QTableWidgetItem(product_name)
            self.version_table.setItem(i, 2, product_item)
            
            # PART ID
            part_id = version.get("part_id", "")
            part_id_item = QTableWidgetItem(part_id)
            self.version_table.setItem(i, 3, part_id_item)
            
            # Start Date - NEW FIELD
            start_date = version.get("start_date", "")
            start_date_item = QTableWidgetItem(start_date)
            self.version_table.setItem(i, 4, start_date_item)
            
            # End Date - NEW FIELD
            end_date = version.get("end_date", "")
            end_date_item = QTableWidgetItem(end_date)
            self.version_table.setItem(i, 5, end_date_item)
            
            # Change summary - Changed index
            summary_item = QTableWidgetItem(version["summary"])
            self.version_table.setItem(i, 6, summary_item)
            
            # Status - Changed index
            status = "Current Version" if version["version"] == active_version else ""
            status_item = QTableWidgetItem(status)
            if status:
                status_item.setForeground(QColor("#00AA00"))  # Green color for current version
            self.version_table.setItem(i, 7, status_item)
    
    def on_version_double_clicked(self, index):
        """Triggered when a version is double-clicked"""
        row = index.row()
        version = self.versions[row]["version"]
        self.version_activated.emit(version)
    
    def activate_selected_version(self):
        """Set selected version as current version"""
        selected_items = self.version_table.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Warning", "Please select a version first")
            return
        
        row = selected_items[0].row()
        version = self.versions[row]["version"]
        self.version_activated.emit(version)
        self.accept()


class ExportReportDialog(QDialog):
    """Export report dialog"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export Version Report")
        self.setMinimumWidth(700)
        self.setMinimumHeight(400)
        self.initUI()
    
    def initUI(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        
        # Export format selection
        format_group = QGroupBox("Report Format")
        format_group.setStyleSheet("QGroupBox { font-weight: bold; }") # Removed font size
        format_layout = QVBoxLayout()
        format_layout.setContentsMargins(20, 30, 20, 20)
        format_layout.setSpacing(15)
        
        self.format_txt = QRadioButton("Text Format (.txt)")
        self.format_csv = QRadioButton("CSV Format (.csv)")
        self.format_pdf = QRadioButton("PDF Format (.pdf)")
        
        self.format_txt.setMinimumHeight(30)
        self.format_csv.setMinimumHeight(30)
        self.format_pdf.setMinimumHeight(30)
        # self.format_txt.setStyleSheet("font-size: 16px;") # Removed font size
        # self.format_csv.setStyleSheet("font-size: 16px;") # Removed font size
        # self.format_pdf.setStyleSheet("font-size: 16px;") # Removed font size
        
        self.format_txt.setChecked(True)  # Default to text format
        
        format_layout.addWidget(self.format_txt)
        format_layout.addWidget(self.format_csv)
        format_layout.addWidget(self.format_pdf)
        
        format_group.setLayout(format_layout)
        layout.addWidget(format_group)
        
        # Output options
        output_group = QGroupBox("Output Options")
        output_group.setStyleSheet("QGroupBox { font-weight: bold; }") # Removed font size
        output_layout = QVBoxLayout()
        output_layout.setContentsMargins(20, 30, 20, 20)
        output_layout.setSpacing(15)
        
        self.include_hash = QCheckBox("Include file hash")
        self.include_hash.setMinimumHeight(30)
        # self.include_hash.setStyleSheet("font-size: 16px;") # Removed font size
        self.include_hash.setChecked(True)
        
        output_layout.addWidget(self.include_hash)
        
        output_group.setLayout(output_layout)
        layout.addWidget(output_group)
        
        # Buttons section
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(20)
        
        self.cancel_button = QPushButton("Cancel")
        self.export_button = QPushButton("Export")
        self.cancel_button.setMinimumWidth(200)
        self.cancel_button.setMinimumHeight(30)
        self.export_button.setMinimumWidth(200)
        self.export_button.setMinimumHeight(30)
        # self.cancel_button.setStyleSheet("font-size: 18px;") # Removed font size
        # self.export_button.setStyleSheet("font-size: 18px;") # Removed font size
        
        self.cancel_button.clicked.connect(self.reject)
        self.export_button.clicked.connect(self.accept)
        
        buttons_layout.addStretch()
        buttons_layout.addWidget(self.cancel_button)
        buttons_layout.addWidget(self.export_button)
        
        layout.addLayout(buttons_layout)
        self.setLayout(layout)
    
    def get_export_format(self):
        """Get selected export format"""
        if self.format_txt.isChecked():
            return "txt"
        elif self.format_csv.isChecked():
            return "csv"
        elif self.format_pdf.isChecked():
            return "pdf"
        return "txt"  # Default


class BackupDialog(QDialog):
    """Backup dialog for specifying the backup location"""
    
    def __init__(self, default_dir, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Backup")
        self.setMinimumWidth(800)
        self.setMinimumHeight(300)
        
        self.default_dir = default_dir
        self.backup_path = ""
        
        self.initUI()
    
    def initUI(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        
        # Add information label
        info_label = QLabel("Select a location to save the backup file:")
        info_label.setStyleSheet("font-weight: bold;") # Removed font size
        layout.addWidget(info_label)
        
        # Create path selection layout
        path_layout = QHBoxLayout()
        path_layout.setSpacing(15)
        
        # Path input field
        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        self.path_edit.setMinimumHeight(30)
        # self.path_edit.setStyleSheet("font-size: 16px;") # Removed font size
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        default_path = os.path.join(self.default_dir, "backups", f"backup_{timestamp}.zip")
        self.path_edit.setText(default_path)
        self.backup_path = default_path
        
        # Browse button
        self.browse_button = QPushButton("Browse...")
        self.browse_button.setMinimumHeight(30)
        self.browse_button.setMinimumWidth(150)
        # self.browse_button.setStyleSheet("font-size: 16px;") # Removed font size
        self.browse_button.clicked.connect(self.browse_location)
        
        path_layout.addWidget(self.path_edit)
        path_layout.addWidget(self.browse_button)
        
        layout.addLayout(path_layout)
        
        # Add description
        description = QLabel(
            "The backup will contain all templates and their versions.\n"
            "You can restore from this backup later if needed."
        )
        description.setStyleSheet("color: #AAAAAA;") # Removed font size
        layout.addWidget(description)
        
        # Add spacing
        layout.addSpacing(20)
        
        # Buttons
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(20)
        
        self.cancel_button = QPushButton("Cancel")
        self.backup_button = QPushButton("Create Backup")
        
        self.cancel_button.setMinimumWidth(180)
        self.cancel_button.setMinimumHeight(30)
        self.backup_button.setMinimumWidth(180)
        self.backup_button.setMinimumHeight(30)
        # self.cancel_button.setStyleSheet("font-size: 18px;") # Removed font size
        # self.backup_button.setStyleSheet("font-size: 18px;") # Removed font size
        
        self.cancel_button.clicked.connect(self.reject)
        self.backup_button.clicked.connect(self.accept)
        
        buttons_layout.addStretch()
        buttons_layout.addWidget(self.cancel_button)
        buttons_layout.addWidget(self.backup_button)
        
        layout.addLayout(buttons_layout)
        
        self.setLayout(layout)
    
    def browse_location(self):
        """Browse for backup location"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Backup", self.backup_path, "ZIP Files (*.zip)"
        )
        
        if file_path:
            self.path_edit.setText(file_path)
            self.backup_path = file_path
    
    def get_backup_path(self):
        """Get the selected backup path"""
        return self.backup_path


class ReadmeDialog(QDialog):
    """Dialog to display README content"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("README - Application Guide")
        self.setMinimumSize(800, 600)
        self.initUI()
        self.load_readme()

    def initUI(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(15, 15, 15, 15)
        
        self.readme_text = QTextEdit()
        self.readme_text.setReadOnly(True)
        self.readme_text.setAcceptRichText(True) # Allow basic markdown rendering
        # self.readme_text.setStyleSheet("font-size: 14px;") # Removed font size
        layout.addWidget(self.readme_text)
        
        close_button = QPushButton("Close")
        close_button.setMinimumHeight(40)
        # close_button.setStyleSheet("font-size: 16px;") # Removed font size
        close_button.clicked.connect(self.accept)
        
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(close_button)
        layout.addLayout(button_layout)
        
        self.setLayout(layout)

    def load_readme(self):
        """Load and display README.md content"""
        readme_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "README.md")
        if os.path.exists(readme_path):
            try:
                with open(readme_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    # Use setMarkdown to render basic markdown
                    self.readme_text.setMarkdown(content) 
            except Exception as e:
                self.readme_text.setPlainText(f"Error loading README.md:\n{e}")
        else:
            self.readme_text.setPlainText("README.md file not found.")


class MainWindow(QMainWindow):
    """Main window class"""
    
    CONFIG_FILE = "VC_config.json"  # 更改配置文件名為 VC_config.json

    # Add base_dir_override=None to the __init__ signature
    def __init__(self, base_dir_override=None): 
        super().__init__()

        # 確定配置文件的絕對路徑
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.CONFIG_FILE = os.path.join(script_dir, "VC_config.json")  # 使用絕對路徑

        # Pass the override to the method that sets the base directory
        self.base_dir = self._get_or_set_base_dir(base_dir_override) 
        # Initialize managers with the determined base directory
        self.version_manager = VersionManager(self.base_dir)
        self.report_generator = ReportGenerator() # Assuming this doesn't need base_dir

        # Set window properties
        self.setWindowTitle("PDF Letterhead Template Management System")
        self.setMinimumSize(1600, 800)
        
        # Initialize UI
        self.initUI()
        
        # Load job/template tree
        self.refresh_job_tree() # Renamed method
    
    def initUI(self):
        # Create central widget
        central_widget = QWidget()
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)
        
        # Create left template list panel
        left_panel = QWidget()
        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(10, 10, 10, 10)
        left_layout.setSpacing(15)
        
        # Template list title
        title_label = QLabel("Jobs & Templates") # Updated Title
        title_label.setStyleSheet("font-weight: bold; padding: 5px;") # Removed font size
        left_layout.addWidget(title_label)
        
        # Search box
        search_layout = QHBoxLayout()
        search_layout.setSpacing(15)
        
        search_label = QLabel("Search:")
        search_label.setMinimumWidth(100)
        # search_label.setStyleSheet("font-size: 18px;") # Removed font size
        
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Enter keywords to filter...")
        self.search_box.setMinimumHeight(30)
        # self.search_box.setStyleSheet("font-size: 18px;") # Removed font size
        self.search_box.textChanged.connect(self.filter_tree) # Renamed filter method
        
        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_box)
        left_layout.addLayout(search_layout)
        
        # Job/Template Tree - UPDATED WITH NEW COLUMNS
        self.job_tree = QTreeWidget()
        self.job_tree.setColumnCount(7)  # Increased column count from 5 to 7
        self.job_tree.setHeaderLabels([
            "Job / Template Name", "Current Version", "Versions", 
            "Product Name", "PART ID", "Start Date", "End Date"
        ])
        self.job_tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems) 
        self.job_tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        # Allow users to resize columns manually
        self.job_tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        # Optionally set initial widths (can be adjusted by user)
        self.job_tree.setColumnWidth(0, 300) # Job / Template Name
        self.job_tree.setColumnWidth(1, 120) # Current Version
        self.job_tree.setColumnWidth(2, 80)  # Versions
        self.job_tree.setColumnWidth(3, 150) # Product Name
        self.job_tree.setColumnWidth(4, 120) # PART ID
        self.job_tree.setColumnWidth(5, 100) # Start Date
        self.job_tree.setColumnWidth(6, 100) # End Date
        self.job_tree.itemClicked.connect(self.on_item_selected)
        self.job_tree.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.job_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.job_tree.customContextMenuRequested.connect(self.show_context_menu)
        # self.job_tree.setStyleSheet("font-size: 18px;") # Removed font size
        self.job_tree.setIndentation(25) 
        
        left_layout.addWidget(self.job_tree) # Add the tree widget
        
        # Template operation buttons
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(15)
        
        self.import_button = QPushButton("Import Template") # Updated text
        self.export_button = QPushButton("Export Report")
        self.delete_button = QPushButton("Delete Item") # Generic text initially
        
        # Make buttons larger
        self.import_button.setMinimumWidth(180)
        self.import_button.setMinimumHeight(30)
        self.export_button.setMinimumWidth(180)
        self.export_button.setMinimumHeight(30)
        self.delete_button.setMinimumWidth(180)
        self.delete_button.setMinimumHeight(30)
        # self.import_button.setStyleSheet("QPushButton { font-size: 24px; }") # Removed font size
        # self.export_button.setStyleSheet("QPushButton { font-size: 24px; }") # Removed font size
        # self.delete_button.setStyleSheet("QPushButton { font-size: 24px; }") # Removed font size
        
        self.import_button.clicked.connect(self.import_template)
        self.export_button.clicked.connect(self.export_report)
        self.delete_button.clicked.connect(self.delete_item) # Connect to unified delete method
        
        # Initially disable buttons that require selection
        self.export_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        
        buttons_layout.addWidget(self.import_button)
        buttons_layout.addWidget(self.export_button)
        buttons_layout.addWidget(self.delete_button)
        buttons_layout.addStretch()
        
        left_layout.addLayout(buttons_layout)
        left_panel.setLayout(left_layout)
        
        # Create right preview and version panel
        right_panel = QWidget()
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(10, 10, 10, 10)
        right_layout.setSpacing(15)
        
        # Add preview title
        preview_header = QHBoxLayout()
        preview_header.setSpacing(15)
        
        self.preview_title = QLabel("Preview")
        self.preview_title.setStyleSheet("font-weight: bold; padding: 5px;") # Removed font size
        preview_header.addWidget(self.preview_title)
        preview_header.addStretch()
        
        self.version_button = QPushButton("Version History")
        self.version_button.setMinimumWidth(180)
        self.version_button.setMinimumHeight(30)
        # self.version_button.setStyleSheet("font-size: 22px;") # Removed font size
        self.version_button.clicked.connect(self.show_version_history)
        self.version_button.setEnabled(False) # Disabled initially
        preview_header.addWidget(self.version_button)
        
        right_layout.addLayout(preview_header)
        
        # Add PDF preview component
        self.preview_widget = PDFPreviewWidget()
        right_layout.addWidget(self.preview_widget)
        
        right_panel.setLayout(right_layout)
        
        # Create splitter with appropriate proportions for A4/Letter size
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        
        # Set initial size ratio favoring the preview panel (closer to A4 proportion)
        splitter.setSizes([650, 1150])  
        
        main_layout.addWidget(splitter)
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)
        
        # Create status bar
        self.statusBar = QStatusBar()
        self.statusBar.setMinimumHeight(40)
        # self.statusBar.setStyleSheet("font-size: 16px; padding: 5px;") # Removed font size
        self.setStatusBar(self.statusBar)
        
        # Display basic information
        self.update_status_bar()

        # Create menu bar
        self.create_menu()

    def _load_config(self) -> Dict:
        """Load configuration from JSON file."""
        if os.path.exists(self.CONFIG_FILE):
            try:
                with open(self.CONFIG_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Could not load config file '{self.CONFIG_FILE}': {e}")
        return {}

    def _save_config(self, config: Dict) -> None:
        """Save configuration to JSON file."""
        try:
            # 確保目錄存在
            config_dir = os.path.dirname(self.CONFIG_FILE)
            if not os.path.exists(config_dir):
                os.makedirs(config_dir)
                
            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4)
                
            print(f"Config saved to: {self.CONFIG_FILE}")
        except IOError as e:
            QMessageBox.critical(self, "Config Error", f"Could not save config file '{self.CONFIG_FILE}': {e}")

    def _get_or_set_base_dir(self) -> str:
        """Gets the base directory from config or prompts the user."""
        config = self._load_config()
        default_dir = os.path.join(os.path.expanduser("~"), "PDFTemplateManager")
        base_dir = config.get("database_path")

        # Validate the path from config
        if base_dir and os.path.isdir(base_dir):
            print(f"Using database path from config: {base_dir}")
            return base_dir
        elif base_dir:
            print(f"Warning: Configured database path '{base_dir}' is not a valid directory.")

        # Prompt user if path is missing or invalid
        print("Database path not found or invalid in config. Prompting user...")
        QMessageBox.information(self, "Database Location",
                                "Please select the folder where you want to store the application data (jobs and templates).")

        selected_dir = QFileDialog.getExistingDirectory(
            self,
            "Select Database Folder",
            default_dir, # Suggest the default
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks
        )

        if selected_dir:
            print(f"User selected database path: {selected_dir}")
            base_dir = selected_dir
        else:
            print("User cancelled selection. Using default path.")
            base_dir = default_dir
            # Ensure default directory exists if user cancelled
            if not os.path.exists(base_dir):
                try:
                    os.makedirs(base_dir)
                except OSError as e:
                     QMessageBox.critical(self, "Directory Error", f"Could not create default directory '{base_dir}': {e}")
                     # Handle this critical error appropriately, maybe exit?
                     sys.exit(1) # Exit if default cannot be created

        # Save the chosen or default path back to config
        config["database_path"] = base_dir
        self._save_config(config)
        return base_dir

    # Add base_dir_override=None to the method signature
    def _get_or_set_base_dir(self, base_dir_override=None) -> str: 
        """Gets the base directory from override, config, or prompts the user."""
        # --- START CHANGE ---
        # Prioritize the override if provided
        if base_dir_override and os.path.isdir(base_dir_override):
            print(f"Using provided base directory: {base_dir_override}")
            # Ensure the directory exists (might be redundant but safe)
            if not os.path.exists(base_dir_override):
                try:
                    os.makedirs(base_dir_override)
                except OSError as e:
                     QMessageBox.critical(self, "Directory Error", f"Could not create provided directory '{base_dir_override}': {e}")
                     sys.exit(1) # Exit if provided dir cannot be created
            return base_dir_override
        elif base_dir_override:
             print(f"Warning: Provided base directory '{base_dir_override}' is not valid. Falling back to config/prompt.")
        # --- END CHANGE ---

        config = self._load_config()
        default_dir = os.path.join(os.path.expanduser("~"), "PDFTemplateManager") # Default for standalone
        base_dir = config.get("database_path")

        # Validate the path from config
        if base_dir and os.path.isdir(base_dir):
            print(f"Using database path from config: {base_dir}")
            return base_dir
        elif base_dir:
            print(f"Warning: Configured database path '{base_dir}' is not a valid directory.")

        # Prompt user if path is missing or invalid (only if no override was given)
        print("Database path not found or invalid in config. Prompting user...")
        QMessageBox.information(self, "Database Location",
                                "Please select the folder where you want to store the application data (jobs and templates).")

        selected_dir = QFileDialog.getExistingDirectory(
            self,
            "Select Database Folder",
            default_dir, # Suggest the default
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks
        )

        if selected_dir:
            print(f"User selected database path: {selected_dir}")
            base_dir = selected_dir
        else:
            print("User cancelled selection. Using default path.")
            base_dir = default_dir
            # Ensure default directory exists if user cancelled
            if not os.path.exists(base_dir):
                try:
                    os.makedirs(base_dir)
                except OSError as e:
                     QMessageBox.critical(self, "Directory Error", f"Could not create default directory '{base_dir}': {e}")
                     sys.exit(1) # Exit if default cannot be created

        # Save the chosen or default path back to config (only if prompted)
        config["database_path"] = base_dir
        self._save_config(config)
        return base_dir

    def create_menu(self):
        """Create menu bar"""
        menubar = self.menuBar()
        # menubar.setStyleSheet("font-size: 16px; padding: 5px;") # Removed font size
        
        # File menu
        file_menu = menubar.addMenu("File")

        new_job_action = QAction("New Job...", self)
        new_job_action.triggered.connect(self.create_new_job)
        file_menu.addAction(new_job_action)
        
        import_action = QAction("Import Template...", self)
        import_action.triggered.connect(self.import_template)
        file_menu.addAction(import_action)
        
        edit_action = QAction("Edit Template Info", self)  # New action
        edit_action.triggered.connect(self.edit_template)
        file_menu.addAction(edit_action)
        
        export_action = QAction("Export Report", self)
        export_action.triggered.connect(self.export_report)
        file_menu.addAction(export_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Tools menu
        tools_menu = menubar.addMenu("Tools")
        
        backup_action = QAction("Create Backup...", self)
        backup_action.triggered.connect(self.create_backup)
        tools_menu.addAction(backup_action)
        
        verify_action = QAction("Verify Integrity...", self)
        verify_action.triggered.connect(self.verify_integrity)
        tools_menu.addAction(verify_action)
        
        # README button (added to the right of Tools menu)
        readme_action = QAction("README", self)
        readme_action.triggered.connect(self.show_readme)
        menubar.addAction(readme_action)
    
    def show_context_menu(self, position):
        """Show context menu for the job/template tree"""
        menu = QMenu()
        # menu.setStyleSheet("font-size: 16px;") # Removed font size
        
        current_item = self.job_tree.currentItem()
        item_data = current_item.data(0, Qt.ItemDataRole.UserRole) if current_item else None
        item_type = item_data.get("type") if item_data else None

        # Common actions
        new_job_action = menu.addAction("New Job...")
        import_template_action = menu.addAction("Import Template...")
        menu.addSeparator()

        # Context-specific actions
        view_history_action = menu.addAction("Version History")
        edit_template_action = menu.addAction("Edit Template Info")  # New action
        export_action = menu.addAction("Export Report")
        menu.addSeparator()
        delete_job_action = menu.addAction("Delete Job")
        delete_template_action = menu.addAction("Delete Template")

        # Enable/disable based on selection
        if item_type == "template":
            view_history_action.setEnabled(True)
            edit_template_action.setEnabled(True)  # Enable for templates
            export_action.setEnabled(True)
            delete_job_action.setEnabled(False)
            delete_template_action.setEnabled(True)
        elif item_type == "job":
            view_history_action.setEnabled(False)
            edit_template_action.setEnabled(False)  # Disable for jobs
            export_action.setEnabled(True) # Enable export for jobs
            delete_job_action.setEnabled(True)
            delete_template_action.setEnabled(False)
        else: # No selection or invalid
            view_history_action.setEnabled(False)
            edit_template_action.setEnabled(False)  # Disable when no selection
            export_action.setEnabled(False)
            delete_job_action.setEnabled(False)
            delete_template_action.setEnabled(False)

        # Show context menu at the cursor position
        action = menu.exec_(self.job_tree.mapToGlobal(position))
        
        # Handle selected action
        if action == new_job_action:
            self.create_new_job()
        elif action == import_template_action:
            self.import_template()
        elif action == view_history_action and item_type == "template":
            self.show_version_history()
        elif action == edit_template_action and item_type == "template":
            self.edit_template()  # Call new method
        elif action == export_action and item_type == "template":
            self.export_report()
        elif action == delete_job_action and item_type == "job":
            self.delete_item()
        elif action == delete_template_action and item_type == "template":
            self.delete_item()

    def refresh_job_tree(self):
        """Refresh job/template tree"""
        
        # --- State Preservation ---
        # Keep track of expanded jobs to restore state
        expanded_jobs = set()
        for i in range(self.job_tree.topLevelItemCount()): 
            job_item = self.job_tree.topLevelItem(i)
            if job_item and job_item.isExpanded(): 
                expanded_jobs.add(job_item.text(0))

        # Remember selected item path (job, template)
        selected_path = None
        current_item = self.job_tree.currentItem()
        if current_item:
            item_data = current_item.data(0, Qt.ItemDataRole.UserRole)
            if item_data:
                if item_data.get("type") == "template":
                    selected_path = (item_data.get("job_name"), item_data.get("template_name"))
                elif item_data.get("type") == "job":
                    selected_path = (item_data.get("job_name"), None)
        
        # --- Clear and Repopulate ---
        self.job_tree.clear()
        jobs = self.version_manager.get_all_jobs()
        
        # Font for job items
        job_font = QFont()
        job_font.setBold(True)
        # job_font.setPointSize(10) # Removed font size setting

        selected_item_to_restore = None

        for job_name in jobs:
            job_item = QTreeWidgetItem(self.job_tree)
            job_item.setText(0, job_name)
            job_item.setFont(0, job_font)
            
            # Set job background color (darker than templates)
            job_item.setBackground(0, QColor(62, 62, 66))
            job_item.setBackground(1, QColor(62, 62, 66))
            job_item.setBackground(2, QColor(62, 62, 66))
            job_item.setBackground(3, QColor(62, 62, 66))  
            job_item.setBackground(4, QColor(62, 62, 66))  
            job_item.setBackground(5, QColor(62, 62, 66))  # For Start Date
            job_item.setBackground(6, QColor(62, 62, 66))  # For End Date
            
            # Add some spacing before and after job items (visual enhancement)
            job_item.setSizeHint(0, QSize(job_item.sizeHint(0).width(), 50))
            
            job_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "job", "job_name": job_name}) # Store type and name

            templates = self.version_manager.get_templates_for_job(job_name)
            for template in templates:
                template_item = QTreeWidgetItem(job_item)
                template_name = template["name"]
                active_version = template.get("active_version", "-")
                versions_count = template.get("versions_count", 0)
                product_name = template.get("product_name", "")  
                part_id = template.get("part_id", "")            
                start_date = template.get("start_date", "")      # Get new field
                end_date = template.get("end_date", "")          # Get new field
                
                template_item.setText(0, template_name)
                template_item.setText(1, active_version)
                template_item.setText(2, str(versions_count))
                template_item.setText(3, product_name)
                template_item.setText(4, part_id)
                template_item.setText(5, start_date)             # Display Start Date
                template_item.setText(6, end_date)               # Display End Date
                template_item.setToolTip(0, f"Job: {job_name}\nTemplate: {template_name}\nProduct: {product_name}\nPART ID: {part_id}\nValid: {start_date} ~ {end_date}")
                
                # Set template background color (lighter than jobs)
                template_item.setBackground(0, QColor(37, 37, 38))
                template_item.setBackground(1, QColor(37, 37, 38))
                template_item.setBackground(2, QColor(37, 37, 38))
                template_item.setBackground(3, QColor(37, 37, 38))
                template_item.setBackground(4, QColor(37, 37, 38))
                template_item.setBackground(5, QColor(37, 37, 38))  # For Start Date
                template_item.setBackground(6, QColor(37, 37, 38))  # For End Date
                
                # Store type, job name, and template name
                template_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "template", "job_name": job_name, "template_name": template_name})

                # Check if this item should be re-selected
                if selected_path and selected_path == (job_name, template_name):
                    selected_item_to_restore = template_item

            # Restore expansion state
            if job_name in expanded_jobs:
                job_item.setExpanded(True)

            # Check if the job item itself should be re-selected
            if selected_path and selected_path == (job_name, None):
                selected_item_to_restore = job_item

        # --- Restore Selection ---
        if selected_item_to_restore:
            self.job_tree.setCurrentItem(selected_item_to_restore)
            # Ensure the selected item is visible
            self.job_tree.scrollToItem(selected_item_to_restore, QAbstractItemView.ScrollHint.PositionAtCenter)
        
        self.update_status_bar() # Update status after refresh

    def filter_tree(self): # Renamed from filter_templates
        """Filter job/template tree based on search box"""
        search_text = self.search_box.text().lower()
        
        iterator = QTreeWidgetItemIterator(self.job_tree) # Standard iterator
        while iterator.value():
            item = iterator.value()
            item_data = item.data(0, Qt.ItemDataRole.UserRole)
            item_type = item_data.get("type") if item_data else None
            
            item_matches = False
            if not search_text: # If search is empty, show everything
                item_matches = True
            elif item_type == "job":
                job_name = item_data.get("job_name", "").lower()
                item_matches = search_text in job_name
            elif item_type == "template":
                # Check all relevant columns for templates
                template_name = item.text(0).lower() # Column 0: Template Name
                product_name = item.text(3).lower()  # Column 3: Product Name
                part_id = item.text(4).lower()       # Column 4: PART ID
                start_date = item.text(5).lower()    # Column 5: Start Date
                end_date = item.text(6).lower()      # Column 6: End Date
                
                item_matches = (
                    search_text in template_name or
                    search_text in product_name or
                    search_text in part_id or
                    search_text in start_date or
                    search_text in end_date
                )

            # Basic visibility based on item match
            item.setHidden(not item_matches)

            # Ensure parent is visible if child matches
            if item_matches and item.parent():
                 item.parent().setHidden(False)
                 # Also expand parent if searching and a child matches
                 if item_matches and search_text:
                     item.parent().setExpanded(True)

            iterator += 1

        # Second pass: Hide jobs that have no visible children (unless the job itself matches the search)
        if search_text: # Only do this when filtering
            # Iterate through top-level items only for the second pass
            for i in range(self.job_tree.topLevelItemCount()):
                job_item = self.job_tree.topLevelItem(i)
                if not job_item: continue # Skip if item somehow doesn't exist

                # Check if the job item itself matches the search
                job_data = job_item.data(0, Qt.ItemDataRole.UserRole)
                job_name = job_data.get("job_name", "").lower()
                job_matches_search = search_text in job_name

                # Check if it has any visible children after the first pass
                has_visible_child = False
                for j in range(job_item.childCount()):
                    child = job_item.child(j)
                    if child and not child.isHidden(): # Check if child exists and is visible
                        has_visible_child = True
                        break
                
                # Hide the job if it doesn't match the search itself AND has no visible children
                if not has_visible_child and not job_matches_search:
                    job_item.setHidden(True)
                else:
                    # Ensure job is visible if it matches or has visible children
                    job_item.setHidden(False) 
        else:
             # Ensure all jobs are visible when search is cleared
             for i in range(self.job_tree.topLevelItemCount()):
                 job_item = self.job_tree.topLevelItem(i)
                 if job_item:
                     job_item.setHidden(False)


    def update_status_bar(self):
        """Update status bar information"""
        total_jobs = 0
        total_templates = 0
        # Iterate through top-level items only
        for i in range(self.job_tree.topLevelItemCount()):
             job_item = self.job_tree.topLevelItem(i)
             if job_item: # Check if item exists
                 total_jobs += 1
                 total_jobs += 1
                 total_templates += job_item.childCount()

        # Build status message - Uses self.base_dir which is now correctly set
        status_message = f"Jobs: {total_jobs} | Total Templates: {total_templates} | Storage Path: {self.base_dir}"

        self.statusBar.showMessage(status_message)

    def on_item_selected(self, item, column): # Renamed from on_template_selected
        """Triggered when a job or template item is selected"""
        if not item: # No item selected
            self.export_button.setEnabled(False)
            self.delete_button.setEnabled(False) # This button needs context (job or template)
            self.version_button.setEnabled(False)
            self.preview_title.setText("Preview")
            if self.preview_widget.current_doc:
                self.preview_widget.current_doc.close()
                self.preview_widget.current_doc = None
                self.preview_widget.preview_label.clear()
            return

        item_data = item.data(0, Qt.ItemDataRole.UserRole)
        item_type = item_data.get("type") if item_data else None
        
        if item_type == "template":
            job_name = item_data.get("job_name")
            template_name = item_data.get("template_name")
            
            # Enable template-specific actions
            self.export_button.setEnabled(True)
            self.delete_button.setEnabled(True) # Context: Delete Template
            self.delete_button.setText("Delete Template") # Update button text
            self.version_button.setEnabled(True)

            # Load preview for the active version
            active_version = self.version_manager.get_active_version(job_name, template_name)
            if active_version:
                self.preview_title.setText(f"Preview: {job_name} / {template_name} (v{active_version['version']})")
                pdf_path = self.version_manager.get_version_path(job_name, template_name, active_version['version'])
                self.preview_widget.load_pdf(pdf_path)
            else:
                self.preview_title.setText(f"Preview: {job_name} / {template_name} (No Active Version)")
                if self.preview_widget.current_doc:
                    self.preview_widget.current_doc.close()
                    self.preview_widget.current_doc = None
                self.preview_widget.preview_label.clear() # Clear preview only if no active version

        elif item_type == "job":
            job_name = item_data.get("job_name")
            # Enable job-specific actions
            self.export_button.setEnabled(True) # Enable export for jobs
            self.delete_button.setEnabled(True) # Context: Delete Job
            self.delete_button.setText("Delete Job") # Update button text
            self.version_button.setEnabled(False) # No version history for a job
            
            # Clear preview
            self.preview_title.setText(f"Job Selected: {job_name}")
            if self.preview_widget.current_doc:
                self.preview_widget.current_doc.close()
                self.preview_widget.current_doc = None
                self.preview_widget.preview_label.clear()
        else:
            # Invalid item or no selection
            self.export_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            self.version_button.setEnabled(False)
            self.preview_title.setText("Preview")
            if self.preview_widget.current_doc:
                self.preview_widget.current_doc.close()
                self.preview_widget.current_doc = None
                self.preview_widget.preview_label.clear()

    def on_item_double_clicked(self, item, column): # Renamed from on_template_double_clicked
        """Triggered when a job or template item is double-clicked"""
        if not item: return
        item_data = item.data(0, Qt.ItemDataRole.UserRole)
        item_type = item_data.get("type") if item_data else None

        if item_type == "template":
            self.show_version_history()
        elif item_type == "job":
            # Expand/collapse job item
            item.setExpanded(not item.isExpanded())

    def import_template(self):
        """Import new template into a selected or new job"""
        # --- Get target job ---
        current_item = self.job_tree.currentItem()
        target_job = None
        if current_item:
            item_data = current_item.data(0, Qt.ItemDataRole.UserRole)
            if item_data:
                if item_data.get("type") == "job":
                    target_job = item_data.get("job_name")
                elif item_data.get("type") == "template":
                    target_job = item_data.get("job_name") # Use job of selected template

        all_jobs = self.version_manager.get_all_jobs()

        if not target_job:
            if not all_jobs:
                # No jobs exist, must create one
                new_job_name, ok = QInputDialog.getText(self, "Create New Job", "No jobs exist yet. Enter name for the first job:")
                if ok and new_job_name:
                    try:
                        self.version_manager.create_job(new_job_name)
                        target_job = new_job_name
                        all_jobs.append(target_job) # Add to list for dialog
                        self.refresh_job_tree()
                    except ValueError as e:
                        QMessageBox.warning(self, "Create Job Failed", str(e))
                        return
                else:
                    return # User cancelled
            else:
                # Prompt user to select a job or create new
                job_options = all_jobs + ["<Create New Job...>"]
                selected_option, ok = QInputDialog.getItem(self, "Select Job", "Select target job for the new template:", job_options, 0, False)
                
                if not ok: return # User cancelled

                if selected_option == "<Create New Job...>":
                    new_job_name, ok_new = QInputDialog.getText(self, "Create New Job", "Enter name for the new job:")
                    if ok_new and new_job_name:
                        try:
                            self.version_manager.create_job(new_job_name)
                            target_job = new_job_name
                            self.refresh_job_tree()
                        except ValueError as e:
                            QMessageBox.warning(self, "Create Job Failed", str(e))
                            return
                    else:
                        return # User cancelled new job creation
                else:
                    target_job = selected_option

        if not target_job: # Should have a job by now
            QMessageBox.critical(self, "Error", "Could not determine target job for import.")
            return

        # --- Proceed with import dialog ---
        dialog = ImportTemplateDialog(self)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            import_data = dialog.get_import_data()
            template_name = import_data["template_name"]
            
            try:
                # Check if template name already exists *within the target job*
                if self.version_manager.template_exists(target_job, template_name):
                    reply = QMessageBox.question(
                        self, "Template Already Exists",
                        f"Template '{template_name}' already exists in job '{target_job}'.\nDo you want to add this as a new version?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No
                    )
                    
                    if reply == QMessageBox.StandardButton.No:
                        return
                
                # Add template version to the target job
                # This will create the template if it doesn't exist and add the version
                self.version_manager.add_version(
                    target_job, # Pass the determined job name
                    template_name,
                    import_data["pdf_path"],
                    import_data["version"],
                    import_data["summary"],
                    import_data["product_name"],
                    import_data["part_id"],
                    import_data["start_date"],     # Pass new field
                    import_data["end_date"]        # Pass new field
                )
                
                # Refresh tree
                self.refresh_job_tree()
                
                # Show success message
                QMessageBox.information(
                    self, "Import Successful",
                    f"Template '{template_name}' (Version {import_data['version']}) has been successfully imported into job '{target_job}'."
                )
                
                # Select newly imported template in the tree
                iterator = QTreeWidgetItemIterator(self.job_tree) # Standard iterator
                while iterator.value():
                    item = iterator.value()
                    item_data = item.data(0, Qt.ItemDataRole.UserRole)
                    if item_data and item_data.get("type") == "template" and \
                    item_data.get("job_name") == target_job and \
                    item_data.get("template_name") == template_name:
                        self.job_tree.setCurrentItem(item)
                        self.on_item_selected(item, 0) # Trigger selection logic
                        break
                    iterator += 1
                
            except ValueError as e:
                QMessageBox.warning(self, "Import Failed", str(e))
            except Exception as e:
                QMessageBox.critical(self, "Error", f"An error occurred during import: {e}")
    
    def export_report(self):
        """Export report for the selected job or template"""
        current_item = self.job_tree.currentItem()
        if not current_item:
            QMessageBox.warning(self, "Warning", "Please select a job or template first.")
            return

        item_data = current_item.data(0, Qt.ItemDataRole.UserRole)
        item_type = item_data.get("type") if item_data else None
        job_name = item_data.get("job_name")

        if not item_type:
            QMessageBox.warning(self, "Warning", "Invalid selection.")
            return

        # --- Show export options dialog ---
        dialog = ExportReportDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        export_format = dialog.get_export_format()

        # --- Prepare data and filename based on selection type ---
        report_data = []
        default_filename = ""
        report_level = "" # "Job" or "Template"

        if item_type == "template":
            template_name = item_data.get("template_name")
            versions = self.version_manager.get_template_versions(job_name, template_name)
            if not versions:
                QMessageBox.warning(self, "Warning", f"Template '{template_name}' in job '{job_name}' has no versions.")
                return
            report_data = versions # Data is the list of versions for the template
            default_filename = f"{job_name}_{template_name}_Template_Report.{export_format}"
            report_level = "Template"

        elif item_type == "job":
            templates_in_job = self.version_manager.get_templates_for_job(job_name)
            if not templates_in_job:
                 QMessageBox.warning(self, "Warning", f"Job '{job_name}' contains no templates.")
                 return
                 
            # Aggregate data for all templates in the job
            job_report_data = []
            for template_info in templates_in_job:
                template_name = template_info["name"]
                versions = self.version_manager.get_template_versions(job_name, template_name)
                # Include template metadata along with versions
                job_report_data.append({
                    "name": template_name,
                    "product_name": template_info.get("product_name", ""),
                    "part_id": template_info.get("part_id", ""),
                    "start_date": template_info.get("start_date", ""),
                    "end_date": template_info.get("end_date", ""),
                    "active_version": template_info.get("active_version"),
                    "versions": versions
                })
            report_data = job_report_data # Data is the list of template dictionaries
            default_filename = f"{job_name}_Job_Report.{export_format}"
            report_level = "Job"

        # --- Select save path ---
        file_filter = ""
        if export_format == "txt":
            file_filter = "Text Files (*.txt)"
        elif export_format == "csv":
            file_filter = "CSV Files (*.csv)"
        elif export_format == "pdf":
            file_filter = "PDF Files (*.pdf)"
        
        save_path, _ = QFileDialog.getSaveFileName(
            self, f"Save {report_level} Report", default_filename, file_filter
        )
        
        if not save_path:
            return

        # --- Generate Report ---
        try:
            if report_level == "Template":
                template_name = item_data.get("template_name") # Get template name again
                if export_format == "txt":
                    self.report_generator.generate_text_report(template_name, report_data, save_path)
                elif export_format == "csv":
                    self.report_generator.generate_csv_report(template_name, report_data, save_path)
                elif export_format == "pdf":
                    self.report_generator.generate_pdf_report(template_name, report_data, save_path)
                
                QMessageBox.information(
                    self, "Export Successful",
                    f"Template report for '{template_name}' (Job: '{job_name}') exported to:\n{save_path}"
                )

            elif report_level == "Job":
                if export_format == "txt":
                    self.report_generator.generate_job_text_report(job_name, report_data, save_path)
                elif export_format == "csv":
                    self.report_generator.generate_job_csv_report(job_name, report_data, save_path)
                elif export_format == "pdf":
                    self.report_generator.generate_job_pdf_report(job_name, report_data, save_path)

                QMessageBox.information(
                    self, "Export Successful",
                    f"Job report for '{job_name}' exported to:\n{save_path}"
                )

        except Exception as e:
            QMessageBox.critical(self, "Error", f"An error occurred while exporting the report: {e}")


    def delete_item(self):
        """Delete selected job or template"""
        current_item = self.job_tree.currentItem()
        if not current_item:
            QMessageBox.warning(self, "Warning", "Please select a job or template to delete.")
            return

        item_data = current_item.data(0, Qt.ItemDataRole.UserRole)
        item_type = item_data.get("type") if item_data else None
        job_name = item_data.get("job_name")

        if item_type == "template":
            template_name = item_data.get("template_name")
            reply = QMessageBox.question(
                self, "Confirm Deletion",
                f"Are you sure you want to delete template '{template_name}' from job '{job_name}' and all its versions?\nThis action cannot be undone.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    self.version_manager.delete_template(job_name, template_name)
                    self.refresh_job_tree() # Refresh after deletion
                    # Clear preview and disable buttons as selection is lost
                    self.on_item_selected(None, 0) 
                    QMessageBox.information(self, "Deletion Successful", f"Template '{template_name}' deleted.")
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Error deleting template: {e}")

        elif item_type == "job":
            reply = QMessageBox.question(
                self, "Confirm Deletion",
                f"Are you sure you want to delete job '{job_name}' and ALL templates within it?\nThis action cannot be undone.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    self.version_manager.delete_job(job_name)
                    self.refresh_job_tree() # Refresh after deletion
                    # Clear preview and disable buttons as selection is lost
                    self.on_item_selected(None, 0) 
                    QMessageBox.information(self, "Deletion Successful", f"Job '{job_name}' deleted.")
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Error deleting job: {e}")
        else:
             QMessageBox.warning(self, "Warning", "Invalid item selected for deletion.")


    def show_version_history(self):
        """Show version history dialog for the selected template"""
        current_item = self.job_tree.currentItem()
        if not current_item:
            # This shouldn't happen if button is enabled correctly, but check anyway
            return 
            
        item_data = current_item.data(0, Qt.ItemDataRole.UserRole)
        if not item_data or item_data.get("type") != "template":
            # This also shouldn't happen
            return

        job_name = item_data.get("job_name")
        template_name = item_data.get("template_name")
        
        # Get all versions of the template
        versions = self.version_manager.get_template_versions(job_name, template_name)
        
        if not versions:
            QMessageBox.warning(self, "Warning", f"Template '{template_name}' in job '{job_name}' has no versions.")
            return
        
        # Mark current active version
        active_version_info = self.version_manager.get_active_version(job_name, template_name)
        if active_version_info:
            active_id = active_version_info["version"]
            for version in versions:
                version["active"] = (version["version"] == active_id)
                
                # 確保每個版本都有product_name和part_id (可能從模板元數據中繼承)
                if "product_name" not in version or not version["product_name"]:
                    # 獲取模板元數據以獲取缺失的product_name
                    metadata = self.version_manager._load_template_metadata(job_name, template_name)
                    if "product_name" in metadata and metadata["product_name"]:
                        version["product_name"] = metadata["product_name"]
                
                if "part_id" not in version or not version["part_id"]:
                    # 獲取模板元數據以獲取缺失的part_id
                    metadata = self.version_manager._load_template_metadata(job_name, template_name)
                    if "part_id" in metadata and metadata["part_id"]:
                        version["part_id"] = metadata["part_id"]
        
        # Show version history dialog (Pass job/template context if needed, or modify dialog)
        dialog = VersionHistoryDialog(f"{job_name} / {template_name}", versions, self) 
        # Pass full context to set_active_version
        dialog.version_activated.connect(lambda version: self.set_active_version(job_name, template_name, version)) 
        dialog.exec()
    
    def set_active_version(self, job_name, template_name, version): # Added job_name
        """Set active version for a template within a job"""
        try:
            self.version_manager.set_active_version(job_name, template_name, version)
            
            # Refresh tree
            self.refresh_job_tree()
            
            # Update preview (re-select the item to trigger on_item_selected)
            iterator = QTreeWidgetItemIterator(self.job_tree) # Standard iterator
            while iterator.value():
                item = iterator.value()
                item_data = item.data(0, Qt.ItemDataRole.UserRole)
                if item_data and item_data.get("type") == "template" and \
                   item_data.get("job_name") == job_name and \
                   item_data.get("template_name") == template_name:
                    self.job_tree.setCurrentItem(item)
                    self.on_item_selected(item, 0) # Trigger selection logic
                    break
                iterator += 1
            
            # Show success message
            QMessageBox.information(
                self, "Version Switch",
                f"Template '{template_name}' in job '{job_name}' has been switched to version {version}."
            )
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"An error occurred while switching versions: {e}")

    def create_new_job(self):
         """Prompt user and create a new job"""
         job_name, ok = QInputDialog.getText(self, "Create New Job", "Enter name for the new job:")
         if ok and job_name:
             try:
                 self.version_manager.create_job(job_name)
                 self.refresh_job_tree()
                 # Optionally select the new job item
                 # Iterate through top-level items only
                 for i in range(self.job_tree.topLevelItemCount()):
                     item = self.job_tree.topLevelItem(i)
                     if item and item.text(0) == job_name:
                         self.job_tree.setCurrentItem(item)
                         break
             except ValueError as e:
                 QMessageBox.warning(self, "Create Job Failed", str(e))
             except Exception as e:
                  QMessageBox.critical(self, "Error", f"An error occurred creating the job: {e}")

    def create_backup(self):
        """Create system backup of all jobs with custom location"""
        # Show backup dialog to get custom location
        # Pass the _backups directory as default
        backup_default_dir = os.path.join(self.base_dir, "_backups")
        dialog = BackupDialog(backup_default_dir, self) 
        
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        
        backup_path = dialog.get_backup_path()
        
        try:
            # Create backup with the selected path
            result_path = self.version_manager.create_backup(backup_path)
            
            QMessageBox.information(
                self, "Backup Successful",
                f"System backup has been successfully created:\n{result_path}"
            )
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"An error occurred while creating the backup: {e}")

    def verify_integrity(self):
        """Verify integrity of all templates across all jobs"""
        all_results = self.version_manager.verify_all_integrity()
        
        if not all_results:
            QMessageBox.information(self, "Verify Integrity", "No jobs or templates found to verify.")
            return
        
        errors = []
        for job_name, job_data in all_results.items():
             for template_name, template_results in job_data.items():
                 for version, is_valid in template_results.items():
                     if not is_valid:
                         errors.append(f"Job '{job_name}', Template '{template_name}', Version {version}: Validation Failed")
        
        if errors:
            error_message = "The following items failed validation:\n\n" + "\n".join(errors)
            # Use a text edit in the message box for potentially long lists
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Warning)
            msg_box.setWindowTitle("Integrity Verification Failed")
            msg_box.setText("Some files failed integrity checks.")
            
            text_edit = QTextEdit()
            text_edit.setPlainText(error_message)
            text_edit.setReadOnly(True)
            # Make the text edit expand vertically
            text_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            
            # Add the text edit to the message box layout
            # Access the layout (might be grid or vertical depending on Qt version/style)
            layout = msg_box.layout()
            # Assuming grid layout for standard message boxes
            if hasattr(layout, 'addWidget'): # Check if addWidget exists directly
                 # Add to row 1, column 1, spanning 1 row, 1 column (adjust as needed)
                 layout.addWidget(text_edit, 1, 1, 1, layout.columnCount()) 
            else: # Fallback if layout access is different
                 msg_box.setDetailedText(error_message) # Less ideal formatting

            msg_box.exec()

        else:
            QMessageBox.information(self, "Integrity Verification", "All jobs and templates passed validation.")




    def edit_template(self):
        """Edit selected template information"""
        current_item = self.job_tree.currentItem()
        if not current_item:
            QMessageBox.warning(self, "Warning", "Please select a template first.")
            return
            
        item_data = current_item.data(0, Qt.ItemDataRole.UserRole)
        if not item_data or item_data.get("type") != "template":
            QMessageBox.warning(self, "Warning", "Please select a template (not a job) to edit.")
            return

        job_name = item_data.get("job_name")
        template_name = item_data.get("template_name")
        
        # Get template information
        templates = self.version_manager.get_templates_for_job(job_name)
        template_info = None
        for template in templates:
            if template["name"] == template_name:
                template_info = template
                break
        
        if not template_info:
            QMessageBox.warning(self, "Warning", f"Template '{template_name}' information not found.")
            return
        
        # Show edit dialog
        dialog = EditTemplateDialog(template_info, self)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            updated_data = dialog.get_updated_data()
            
            try:
                # Update template information
                self.version_manager.update_template_info(
                    job_name,
                    template_name,
                    product_name=updated_data["product_name"],
                    part_id=updated_data["part_id"],
                    start_date=updated_data["start_date"],
                    end_date=updated_data["end_date"]
                )
                
                # Refresh tree to show updated information
                self.refresh_job_tree()
                
                # Show success message
                QMessageBox.information(
                    self, "Template Updated",
                    f"Template '{template_name}' information has been successfully updated."
                )
                
                # Re-select the template
                self.select_template_in_tree(job_name, template_name)
                
            except Exception as e:
                QMessageBox.critical(self, "Error", f"An error occurred while updating template information: {e}")
        
    def select_template_in_tree(self, job_name, template_name):
        """Helper method to select a template in the tree"""
        iterator = QTreeWidgetItemIterator(self.job_tree)
        while iterator.value():
            item = iterator.value()
            item_data = item.data(0, Qt.ItemDataRole.UserRole)
            if item_data and item_data.get("type") == "template" and \
            item_data.get("job_name") == job_name and \
            item_data.get("template_name") == template_name:
                self.job_tree.setCurrentItem(item)
                self.on_item_selected(item, 0)
                break
            iterator += 1
    
    def show_readme(self):
        """Show README content in a dialog"""
        dialog = ReadmeDialog(self)
        dialog.exec()


def apply_dark_theme(app):
    """Apply dark theme to the application"""
    dark_palette = QPalette()
    
    # Set color for different roles in dark theme
    dark_palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Base, QColor(35, 35, 35))
    dark_palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(25, 25, 25))
    dark_palette.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
    dark_palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)
    
    # Apply palette to application
    app.setPalette(dark_palette)
    
    # Apply additional stylesheet for modern look
    # Updated stylesheet for QTreeWidget with enhanced job/template distinction
    app.setStyleSheet("""
        QMainWindow {
            background-color: #2D2D30;
        }
        QDialog {
            background-color: #2D2D30;
        }
        QWidget {
            color: #FFFFFF;
            background-color: #2D2D30;
        }
        QTreeWidget {
            background-color: #252526;
            border: 1px solid #5A5A5A;
            border-radius: 4px;
            selection-background-color: #007ACC;
            selection-color: white;
            /* font-size: 18px; */ /* Base font size for tree - REMOVED */
            alternate-background-color: #2D2D30; /* For alternating row colors if enabled */
        }
        /* Enhanced styling for top-level job items */
        QTreeWidget::item:has-children {
            background-color: #3E3E42; /* Darker background for job items */
            border: 1px solid #5A5A5A;
            border-radius: 4px;
            margin-top: 8px; /* Add spacing between jobs */
            margin-bottom: 2px;
            padding: 10px 8px; /* More padding for job items */
            font-weight: bold;
        }
        /* Hover effect for job items */
        QTreeWidget::item:has-children:hover {
            background-color: #505054;
        }
        /* Selected job item */
        QTreeWidget::item:has-children:selected {
            background-color: #007ACC;
            color: white;
        }
        /* Template items (children of job items) */
        QTreeWidget::item:!has-children {
            background-color: #252526; /* Lighter background for template items */
            border-bottom: 1px solid #3A3A3A; /* Separator line */
            padding: 8px;
            padding-left: 20px; /* Indent templates more */
            margin-left: 15px; /* Indent from the left edge */
            margin-right: 5px; /* Small margin on right */
        }
        /* Hover effect for template items */
        QTreeWidget::item:!has-children:hover {
            background-color: #3A3A3A;
        }
        /* Selected template item */
        QTreeWidget::item:!has-children:selected {
            background-color: #007ACC;
            color: white;
        }
        QTreeView::branch { /* Style for expand/collapse arrows */
            background: transparent;
        }
        QTreeView::branch:has-children:!has-siblings:closed,
        QTreeView::branch:closed:has-children:has-siblings {
                border-image: none;
                image: url(icons/branch-closed.png); /* Provide path to icon */
        }
        QTreeView::branch:open:has-children:!has-siblings,
        QTreeView::branch:open:has-children:has-siblings  {
                border-image: none;
                image: url(icons/branch-open.png); /* Provide path to icon */
        }
        QHeaderView::section { /* Style for Tree header */
            background-color: #3E3E42;
            color: white;
            border: 1px solid #5A5A5A;
            padding: 10px; 
            /* font-size: 18px; */ /* REMOVED */
            font-weight: bold;
        }
        QPushButton {
            background-color: #0078D7;
            color: white;
            border-radius: 4px;
            padding: 10px 20px;
            border: none;
            /* font-size: 16px; */ /* REMOVED */
        }
        QPushButton:hover {
            background-color: #1C86E0;
        }
        QPushButton:pressed {
            background-color: #005BA1;
        }
        QPushButton:disabled {
            background-color: #3A3A3A;
            color: #848484;
        }
        QLineEdit {
            background-color: #252526;
            border: 1px solid #3F3F46;
            border-radius: 4px;
            color: white;
            padding: 10px;
            /* font-size: 16px; */ /* REMOVED */
        }
        QGroupBox {
            border: 1px solid #3F3F46;
            border-radius: 4px;
            margin-top: 15px;
            padding-top: 15px;
            /* font-size: 18px; */ /* REMOVED */
            font-weight: bold;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top center;
            padding: 0 8px;
        }
        QComboBox {
            background-color: #252526;
            border: 1px solid #3F3F46;
            border-radius: 4px;
            color: white;
            padding: 10px;
            min-width: 6em;
            /* font-size: 16px; */ /* REMOVED */
        }
        QMenu {
            background-color: #2D2D30;
            border: 1px solid #3F3F46;
            /* font-size: 16px; */ /* REMOVED */
            padding: 5px;
        }
        QMenu::item {
            padding: 10px 20px 10px 20px;
        }
        QMenu::item:selected {
            background-color: #007ACC;
        }
        QStatusBar {
            background-color: #007ACC;
            color: white;
            padding: 5px;
            /* font-size: 16px; */ /* REMOVED */
        }
        QCheckBox {
            spacing: 10px;
            /* font-size: 16px; */ /* REMOVED */
        }
        QRadioButton {
            spacing: 10px;
            /* font-size: 16px; */ /* REMOVED */
        }
        QLabel {
            /* font-size: 16px; */ /* REMOVED */
        }
        QSplitter::handle {
            background-color: #3F3F46;
        }
        QSplitter::handle:horizontal {
            width: 3px;
        }
        QSplitter::handle:vertical {
            height: 3px;
        }
        QScrollBar:vertical {
            border: none;
            background: #2D2D30;
            width: 14px;
            margin: 15px 0 15px 0;
        }
        QScrollBar::handle:vertical {
            background: #5A5A5A;
            min-height: 30px;
            border-radius: 7px;
        }
        QScrollBar::handle:vertical:hover {
            background: #7A7A7A;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            border: none;
            background: none;
            height: 15px;
            subcontrol-position: top;
            subcontrol-origin: margin;
        }
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
            background: none;
        }
        QScrollBar:horizontal {
            border: none;
            background: #2D2D30;
            height: 14px;
            margin: 0px 15px 0 15px;
        }
        QScrollBar::handle:horizontal {
            background: #5A5A5A;
            min-width: 30px;
            border-radius: 7px;
        }
        QScrollBar::handle:horizontal:hover {
            background: #7A7A7A;
        }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
            border: none;
            background: none;
            width: 15px;
            subcontrol-position: left;
            subcontrol-origin: margin;
        }
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
            background: none;
        }
        QMessageBox {
            /* font-size: 16px; */ /* REMOVED */
        }
        QMessageBox QPushButton {
            min-width: 120px;
            min-height: 40px;
        }
        QFileDialog QPushButton {
            min-width: 120px;
            min-height: 30px;
        }
    """)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # Use Fusion style for a unified UI appearance
    
    # Apply dark theme
    apply_dark_theme(app)
    
    #Set application icon and style
    # Make sure 'icon.png' exists or remove this line
    app.setWindowIcon(QIcon(str(resource_path("App_icon", "version_PM.png"))))  
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
