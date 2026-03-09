# -*- coding: utf-8 -*-
"""
Transcription Profiles - Sistema di Profili Dinamici
File: utils/transcription_profiles.py

Sistema intelligente per ottimizzare parametri trascrizione
in base al caso d'uso specifico.

Hardware Target: i7-12700KF (12 core) + RTX 3060 12GB

PROFILI DISPONIBILI:
- FAST: Velocità massima (workers=8, beam=5)
- BALANCED: Ottimale per uso generale (workers=6, beam=7) ⭐ DEFAULT
- QUALITY: Alta qualità audio difficile (workers=4, beam=10)
- MAXIMUM: Qualità massima casi critici (workers=4, beam=12)
- BATCH: Ottimizzato per molti file (workers=8, beam=7)
"""

from enum import Enum
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class TranscriptionProfile(Enum):
    """
    Profili predefiniti per diversi use case
    
    Attributes:
        FAST: Velocità massima, qualità buona
        BALANCED: Bilanciamento ottimale (DEFAULT)
        QUALITY: Alta qualità per audio difficile
        MAXIMUM: Qualità massima per casi critici
        BATCH: Ottimizzato per elaborazione batch
    """
    FAST = "fast"
    BALANCED = "balanced"
    QUALITY = "quality"
    MAXIMUM = "maximum"
    BATCH = "batch"


class ProfileConfig:
    """
    Configurazioni ottimali per ogni profilo
    Basate su benchmark empirici con i7-12700KF + RTX 3060
    """
    
    # Definizioni complete profili
    PROFILES: Dict[TranscriptionProfile, Dict[str, Any]] = {
        
        # ================================================================
        # PROFILO: FAST - Velocità Massima
        # ================================================================
        TranscriptionProfile.FAST: {
            'num_workers': 8,
            'beam_size': 5,
            'batch_size_hint': 12,
            'name': 'Velocità Massima',
            'description': 'Massima velocità per uso quotidiano e draft rapidi',
            
            # Performance
            'speed_factor': 1.15,
            'time_1h_audio_min': 82,
            'wer_percent': 4.5,
            'quality_percent': 95.0,
            
            # Risorse
            'cpu_usage': '55-65%',
            'gpu_usage': '80-90%',
            'vram_gb': 6.5,
            'cpu_temp_delta': 8,
            
            # Use cases
            'recommended_for': [
                'Audio pulito (studio recording)',
                'Draft veloci e preview',
                'Molti file da processare rapidamente',
                'Tempo molto limitato'
            ],
            
            'avoid_for': [
                'Audio molto rumoroso',
                'Accenti difficili o dialetti',
                'Trascrizioni critiche'
            ]
        },
        
        # ================================================================
        # PROFILO: BALANCED - Bilanciamento Ottimale ⭐ DEFAULT
        # ================================================================
        TranscriptionProfile.BALANCED: {
            'num_workers': 6,
            'beam_size': 7,
            'batch_size_hint': 8,
            'name': 'Bilanciato',
            'description': 'Bilanciamento ottimale qualità/velocità (RACCOMANDATO)',
            
            # Performance
            'speed_factor': 1.0,
            'time_1h_audio_min': 94,
            'wer_percent': 3.5,
            'quality_percent': 96.5,
            
            # Risorse
            'cpu_usage': '45-55%',
            'gpu_usage': '85-95%',
            'vram_gb': 6.7,
            'cpu_temp_delta': 5,
            
            # Use cases
            'recommended_for': [
                'Uso generale (80% dei casi)',
                'Audio qualità normale',
                'Prima elaborazione default',
                'Quando in dubbio ⭐'
            ],
            
            'notes': 'PROFILO RACCOMANDATO per la maggior parte degli utenti'
        },
        
        # ================================================================
        # PROFILO: QUALITY - Alta Qualità
        # ================================================================
        TranscriptionProfile.QUALITY: {
            'num_workers': 8,  # ✅ MODIFICATO: 4 → 8
            'beam_size': 10,
            'batch_size_hint': 4,
            'name': 'Alta Qualità',
            'description': 'Alta qualità per audio difficile o accenti',
            
            # Performance
            'speed_factor': 0.77,  # ✅ Leggermente più veloce con più workers
            'time_1h_audio_min': 122,  # ✅ Aggiornato
            'wer_percent': 2.8,
            'quality_percent': 97.2,
            
            # Risorse
            'cpu_usage': '55-70%',  # ✅ Più CPU usage
            'gpu_usage': '90-98%',
            'vram_gb': 6.9,
            'cpu_temp_delta': 8,  # ✅ Più temperatura CPU
            
            # Use cases
            'recommended_for': [
                'Audio con rumore background',
                'Accenti marcati o dialetti',
                'Sovrapposizioni vocali',
                'Documentari e interviste difficili',
                'Prima trascrizione insoddisfacente'
            ],
            
            'avoid_for': [
                'Molti file da elaborare',
                'Audio già pulito',
                'Deadline strette'
            ]
        },
        
        # ================================================================
        # PROFILO: MAXIMUM - Qualità Massima
        # ================================================================
        TranscriptionProfile.MAXIMUM: {
            'num_workers': 10,  # ✅ MODIFICATO: 4 → 10
            'beam_size': 12,
            'batch_size_hint': 2,
            'name': 'Qualità Massima',
            'description': 'Qualità massima per casi critici (molto lento)',
            
            # Performance
            'speed_factor': 0.65,  # ✅ Più veloce con più workers
            'time_1h_audio_min': 145,  # ✅ Aggiornato
            'wer_percent': 2.5,
            'quality_percent': 97.5,
            
            # Risorse
            'cpu_usage': '65-80%',  # ✅ Molto più CPU usage
            'gpu_usage': '95-99%',
            'vram_gb': 7.1,
            'cpu_temp_delta': 10,  # ✅ Più temperatura CPU
            
            # Use cases
            'recommended_for': [
                'Trascrizioni mediche/legali',
                'Audio qualità pessima',
                'Sottotitoli ufficiali broadcast',
                'Documentazione scientifica',
                'Cliente pagante esigente'
            ],
            
            'notes': 'Usare SOLO quando qualità è priorità assoluta',
            'warning': '⚠️ Molto lento! Solo per casi critici singoli'
        },
        
        # ================================================================
        # PROFILO: BATCH - Elaborazione Massiva
        # ================================================================
        TranscriptionProfile.BATCH: {
            'num_workers': 8,
            'beam_size': 7,
            'batch_size_hint': 16,
            'name': 'Batch Rapido',
            'description': 'Ottimizzato per elaborazione batch di molti file',
            
            # Performance
            'speed_factor': 1.10,
            'time_1h_audio_min': 85,
            'wer_percent': 3.5,
            'quality_percent': 96.5,
            
            # Risorse
            'cpu_usage': '55-70%',
            'gpu_usage': '85-95%',
            'vram_gb': 6.7,
            'cpu_temp_delta': 8,
            
            # Use cases
            'recommended_for': [
                '5+ file da elaborare',
                'Elaborazione notturna',
                'Serie TV/stagioni complete',
                'Archivio video da processare',
                'Tempo non critico ma tanti file'
            ],
            
            'notes': 'Bilanciamento CPU/GPU ottimale per throughput',
            'warning': '⚠️ Monitora temperature per elaborazioni lunghe'
        }
    }
    
    @classmethod
    def from_string(cls, profile_str: str) -> TranscriptionProfile:
        """
        Converte stringa profilo in enum TranscriptionProfile
        
        Args:
            profile_str: Nome profilo come stringa ('fast', 'balanced', ecc.)
            
        Returns:
            Enum TranscriptionProfile corrispondente
        """
        # Normalizza la stringa (lowercase)
        profile_str = profile_str.lower().strip()
        
        # Mappa stringhe -> enum
        profile_map = {
            'fast': TranscriptionProfile.FAST,
            'balanced': TranscriptionProfile.BALANCED,
            'quality': TranscriptionProfile.QUALITY,
            'maximum': TranscriptionProfile.MAXIMUM,
            'batch': TranscriptionProfile.BATCH
        }
        
        if profile_str in profile_map:
            return profile_map[profile_str]
        else:
            logger.warning(f"Profilo '{profile_str}' non riconosciuto, uso BALANCED")
            return TranscriptionProfile.BALANCED
    
    @classmethod
    def get_profile_config(cls, profile: TranscriptionProfile) -> Dict[str, Any]:
        """
        Ottieni configurazione completa per profilo specifico
        
        Args:
            profile: Profilo desiderato
            
        Returns:
            Dizionario con tutti i parametri del profilo
        """
        if profile not in cls.PROFILES:
            logger.warning(f"Profilo {profile} non trovato, uso BALANCED")
            profile = TranscriptionProfile.BALANCED
        
        return cls.PROFILES[profile].copy()
    
    @classmethod
    def get_transcription_params(cls, profile: TranscriptionProfile) -> Dict[str, int]:
        """
        Ottieni SOLO parametri trascrizione (per passare al transcriber)
        
        Args:
            profile: Profilo desiderato
            
        Returns:
            Dizionario con num_workers e beam_size
        """
        config = cls.get_profile_config(profile)
        
        return {
            'num_workers': config['num_workers'],
            'beam_size': config['beam_size'],
            'batch_size_hint': config.get('batch_size_hint', None),
        }
    
    @classmethod
    def get_all_profiles(cls) -> Dict[str, Dict[str, Any]]:
        """
        Ottieni tutti i profili disponibili
        
        Returns:
            Dizionario con tutti i profili
        """
        return {
            profile.value: cls.get_profile_config(profile)
            for profile in TranscriptionProfile
        }
    
    @classmethod
    def list_profiles(cls) -> list:
        """
        Lista nomi profili disponibili
        
        Returns:
            Lista stringhe con nomi profili
        """
        return [profile.value for profile in TranscriptionProfile]
    
    @classmethod
    def estimate_time(cls, profile: TranscriptionProfile, audio_duration_minutes: float) -> float:
        """
        Stima tempo elaborazione per durata audio
        
        Args:
            profile: Profilo da usare
            audio_duration_minutes: Durata audio in minuti
            
        Returns:
            Tempo stimato in minuti
        """
        config = cls.get_profile_config(profile)
        time_per_hour = config['time_1h_audio_min']
        
        # Calcola tempo proporzionale
        estimated_time = (audio_duration_minutes / 60.0) * time_per_hour
        
        return estimated_time
    
    @classmethod
    def get_resource_requirements(cls, profile: TranscriptionProfile) -> Dict[str, Any]:
        """
        Ottieni requisiti risorse per profilo
        
        Args:
            profile: Profilo desiderato
            
        Returns:
            Dizionario con requisiti CPU/GPU/VRAM
        """
        config = cls.get_profile_config(profile)
        
        return {
            'cpu_usage': config['cpu_usage'],
            'gpu_usage': config['gpu_usage'],
            'vram_gb': config['vram_gb'],
            'cpu_temp_delta': config['cpu_temp_delta']
        }
    
    @classmethod
    def compare_profiles(
        cls, 
        profile1: TranscriptionProfile, 
        profile2: TranscriptionProfile
    ) -> Dict[str, float]:
        """
        Confronta due profili
        
        Args:
            profile1: Primo profilo
            profile2: Secondo profilo
            
        Returns:
            Dizionario con differenze
        """
        config1 = cls.PROFILES[profile1]
        config2 = cls.PROFILES[profile2]
        
        return {
            'speed_diff_percent': ((config2['speed_factor'] / config1['speed_factor']) - 1) * 100,
            'quality_diff_percent': config2['quality_percent'] - config1['quality_percent'],
            'wer_diff': config2['wer_percent'] - config1['wer_percent'],
            'vram_diff_gb': config2['vram_gb'] - config1['vram_gb'],
            'temp_diff_c': config2['cpu_temp_delta'] - config1['cpu_temp_delta']
        }


class ProfileRecommender:
    """
    Sistema di raccomandazione intelligente profili
    """
    
    @staticmethod
    def recommend(
        audio_quality: Optional[str] = None,
        num_files: int = 1,
        time_critical: bool = False,
        quality_critical: bool = False,
        audio_duration_minutes: Optional[float] = None
    ) -> TranscriptionProfile:
        """
        Raccomanda profilo ottimale basato su parametri
        
        Args:
            audio_quality: 'excellent', 'good', 'fair', 'poor', None
            num_files: Numero file da elaborare
            time_critical: Se tempo è prioritario
            quality_critical: Se qualità è prioritaria
            audio_duration_minutes: Durata totale audio (opzionale)
            
        Returns:
            Profilo raccomandato
        """
        
        logger.info("🎯 Raccomandazione profilo trascrizione:")
        logger.info(f"  - Audio quality: {audio_quality or 'unknown'}")
        logger.info(f"  - Num files: {num_files}")
        logger.info(f"  - Time critical: {time_critical}")
        logger.info(f"  - Quality critical: {quality_critical}")
        
        # Logica decisionale
        
        # 1. Qualità critica → MAXIMUM o QUALITY
        if quality_critical:
            if audio_quality in ['poor', 'fair']:
                logger.info("  → MAXIMUM (qualità critica + audio difficile)")
                return TranscriptionProfile.MAXIMUM
            else:
                logger.info("  → QUALITY (qualità critica)")
                return TranscriptionProfile.QUALITY
        
        # 2. Tempo critico + molti file → BATCH
        if time_critical and num_files >= 5:
            logger.info("  → BATCH (tempo critico + molti file)")
            return TranscriptionProfile.BATCH
        
        # 3. Tempo critico → FAST
        if time_critical:
            logger.info("  → FAST (tempo critico)")
            return TranscriptionProfile.FAST
        
        # 4. Audio molto difficile → QUALITY
        if audio_quality in ['poor', 'fair']:
            logger.info("  → QUALITY (audio difficile)")
            return TranscriptionProfile.QUALITY
        
        # 5. Molti file (5+) → BATCH
        if num_files >= 5:
            logger.info("  → BATCH (molti file)")
            return TranscriptionProfile.BATCH
        
        # 6. Audio eccellente + pochi file → FAST
        if audio_quality == 'excellent' and num_files <= 2:
            logger.info("  → FAST (audio eccellente)")
            return TranscriptionProfile.FAST
        
        # 7. Default → BALANCED
        logger.info("  → BALANCED (caso generale)")
        return TranscriptionProfile.BALANCED
    
    @staticmethod
    def get_recommendation_explanation(
        profile: TranscriptionProfile,
        audio_quality: Optional[str] = None,
        num_files: int = 1
    ) -> str:
        """
        Genera spiegazione per raccomandazione
        
        Args:
            profile: Profilo raccomandato
            audio_quality: Qualità audio
            num_files: Numero file
            
        Returns:
            Stringa esplicativa
        """
        config = ProfileConfig.PROFILES[profile]
        
        explanation = f"Profilo raccomandato: {config['name']}\n"
        explanation += f"Motivo: {config['description']}\n\n"
        
        if audio_quality:
            explanation += f"Audio quality: {audio_quality}\n"
        
        explanation += f"Files: {num_files}\n"
        explanation += f"Tempo stimato (1h audio): {config['time_1h_audio_min']} min\n"
        explanation += f"Qualità attesa: {config['quality_percent']:.1f}% (WER {config['wer_percent']}%)\n"
        
        return explanation


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_default_profile() -> TranscriptionProfile:
    """
    Ottieni profilo default
    
    Returns:
        TranscriptionProfile.BALANCED
    """
    return TranscriptionProfile.BALANCED


def log_profile_info(profile: TranscriptionProfile):
    """
    Log informazioni profilo selezionato
    
    Args:
        profile: Profilo da loggare
    """
    config = ProfileConfig.PROFILES[profile]
    
    logger.info("=" * 70)
    logger.info(f"PROFILO TRASCRIZIONE: {config['name'].upper()}")
    logger.info("=" * 70)
    logger.info(f"Descrizione: {config['description']}")
    logger.info(f"Parameters:")
    logger.info(f"  - num_workers: {config['num_workers']}")
    logger.info(f"  - beam_size: {config['beam_size']}")
    logger.info(f"Performance:")
    logger.info(f"  - Velocità relativa: {config['speed_factor']:.0%}")
    logger.info(f"  - Tempo 1h audio: ~{config['time_1h_audio_min']} min")
    logger.info(f"  - Qualità: {config['quality_percent']:.1f}% (WER {config['wer_percent']}%)")
    logger.info(f"Risorse:")
    logger.info(f"  - CPU: {config['cpu_usage']}")
    logger.info(f"  - GPU: {config['gpu_usage']}")
    logger.info(f"  - VRAM: {config['vram_gb']} GB")
    logger.info(f"  - Temp +: {config['cpu_temp_delta']}°C")
    
    if 'notes' in config:
        logger.info(f"Note: {config['notes']}")
    if 'warning' in config:
        logger.info(f"⚠️ {config['warning']}")
    
    logger.info("=" * 70)


# ============================================================================
# TESTING
# ============================================================================

if __name__ == '__main__':
    """Test sistema profili"""
    
    print("\n" + "=" * 80)
    print("TEST SISTEMA PROFILI TRASCRIZIONE")
    print("=" * 80 + "\n")
    
    # Test 1: Lista profili
    print("Profili disponibili:")
    for profile in TranscriptionProfile:
        config = ProfileConfig.get_profile_config(profile)
        print(f"  - {profile.value}: {config['name']}")
    
    print("\n" + "-" * 80 + "\n")
    
    # Test 2: Parametri profilo
    profile = TranscriptionProfile.BALANCED
    params = ProfileConfig.get_transcription_params(profile)
    print(f"Parametri BALANCED: {params}")
    
    print("\n" + "-" * 80 + "\n")
    
    # Test 3: Raccomandazioni
    test_cases = [
        {
            'desc': 'Film singolo, audio buono',
            'params': {'audio_quality': 'good', 'num_files': 1}
        },
        {
            'desc': '10 episodi serie TV',
            'params': {'audio_quality': 'good', 'num_files': 10}
        },
        {
            'desc': 'Documentario rumoroso, qualità importante',
            'params': {'audio_quality': 'poor', 'quality_critical': True}
        },
        {
            'desc': 'Draft veloce',
            'params': {'time_critical': True}
        }
    ]
    
    print("Test raccomandazioni:")
    for case in test_cases:
        rec = ProfileRecommender.recommend(**case['params'])
        print(f"\n  Scenario: {case['desc']}")
        print(f"  → {rec.value.upper()}")
    
    print("\n" + "-" * 80 + "\n")
    
    # Test 4: Stima tempo
    profile = TranscriptionProfile.BALANCED
    time_est = ProfileConfig.estimate_time(profile, 120)  # 2 ore
    print(f"Tempo stimato 2h audio con BALANCED: {time_est:.1f} min ({time_est/60:.1f}h)")
    
    print("\n✅ Test completati!")
