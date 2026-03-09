"""
Temporary file management - FIXED for FFmpeg whisper
Usa hash invece di nomi video per evitare spazi nei path
"""
import tempfile
import shutil
from pathlib import Path
import logging
import hashlib

class FileHandler:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.temp_base = Path(tempfile.gettempdir()) / 'TranscriberPro'
        self.temp_base.mkdir(exist_ok=True)
        self.temp_dirs = {}
        self.video_hash_map = {}  # Mappa video_name -> hash
    
    def _get_video_hash(self, video_path):
        """
        Genera hash breve (8 caratteri) dal nome video
        Questo evita spazi e caratteri speciali nei path temporanei
        """
        if isinstance(video_path, (str, Path)):
            video_name = Path(video_path).stem
        else:
            video_name = str(video_path)
        
        # Usa hash se non già mappato
        if video_name not in self.video_hash_map:
            # MD5 hash dei primi 8 caratteri
            hash_obj = hashlib.md5(video_name.encode('utf-8'))
            hash_short = hash_obj.hexdigest()[:8]
            self.video_hash_map[video_name] = hash_short
            self.logger.info(f"Video '{video_name}' -> temp dir 'vid_{hash_short}'")
        
        return self.video_hash_map[video_name]
    
    def get_temp_path(self, video_path, filename=None):
        """
        Get a temporary file path for a video
        IMPORTANTE: Usa hash invece del nome video per evitare spazi
        
        Args:
            video_path: Can be either full path or just video name
            filename: Optional filename for the temp file
            
        Returns:
            Path to temp file or temp directory if filename is None
        """
        # Extract video name from path if full path is provided
        if isinstance(video_path, (str, Path)):
            video_name = Path(video_path).stem
        else:
            video_name = str(video_path)
        
        # Usa hash per directory name (niente spazi!)
        video_hash = self._get_video_hash(video_name)
        dir_name = f"vid_{video_hash}"
        
        # Create temp directory if it doesn't exist
        if video_name not in self.temp_dirs:
            temp_dir = self.temp_base / dir_name
            temp_dir.mkdir(exist_ok=True)
            self.temp_dirs[video_name] = temp_dir
            self.logger.debug(f"Created temp dir: {temp_dir}")
        
        # Return directory if no filename specified
        if filename is None:
            return self.temp_dirs[video_name]
        
        # Return full path to file
        return self.temp_dirs[video_name] / filename
    
    def get_temp_dir(self, video_path):
        """
        Get temporary directory for a video
        
        Args:
            video_path: Full path or name of video
            
        Returns:
            Path to temp directory (senza spazi)
        """
        return self.get_temp_path(video_path, filename=None)
    
    def cleanup(self, video_path):
        """
        Clean up temporary files for a video
        
        Args:
            video_path: Full path or name of video
        """
        # Extract video name
        if isinstance(video_path, (str, Path)):
            video_name = Path(video_path).stem
        else:
            video_name = str(video_path)
        
        if video_name in self.temp_dirs:
            temp_dir = self.temp_dirs[video_name]
            if temp_dir.exists():
                try:
                    shutil.rmtree(temp_dir)
                    self.logger.info(f"Cleaned up temp directory: {temp_dir}")
                except Exception as e:
                    self.logger.warning(f"Failed to clean up {temp_dir}: {e}")
            del self.temp_dirs[video_name]
        
        # Rimuovi dalla mappa hash
        if video_name in self.video_hash_map:
            del self.video_hash_map[video_name]
    
    def cleanup_all(self):
        """
        Clean up all temporary files
        """
        # Clean up all tracked directories
        for video_name in list(self.temp_dirs.keys()):
            temp_dir = self.temp_dirs[video_name]
            if temp_dir.exists():
                try:
                    shutil.rmtree(temp_dir)
                    self.logger.info(f"Cleaned up temp directory: {temp_dir}")
                except Exception as e:
                    self.logger.warning(f"Failed to clean up {temp_dir}: {e}")
        
        self.temp_dirs.clear()
        self.video_hash_map.clear()
        
        # Try to clean up base directory if empty
        try:
            if self.temp_base.exists() and not any(self.temp_base.iterdir()):
                shutil.rmtree(self.temp_base)
                self.logger.info("Cleaned up all temporary files")
        except Exception as e:
            self.logger.warning(f"Failed to clean up temp base directory: {e}")
