###############################################################################
#  音频处理工具函数
###############################################################################

import io
import math
import numpy as np

# Cache de disponibilidad de backends de remuestreo
_resample_poly_available = None
_torchaudio_available = None


def pcm_to_float32(pcm_bytes: bytes, sample_width: int = 2) -> np.ndarray:
    """将 PCM bytes 转换为 float32 numpy 数组（范围 [-1.0, 1.0]）"""
    if sample_width == 2:
        data = np.frombuffer(pcm_bytes, dtype=np.int16)
        return data.astype(np.float32) / 32768.0
    elif sample_width == 4:
        data = np.frombuffer(pcm_bytes, dtype=np.int32)
        return data.astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"Unsupported sample width: {sample_width}")


def float32_to_pcm(audio: np.ndarray, sample_width: int = 2) -> bytes:
    """将 float32 numpy 数组转换为 PCM bytes"""
    if sample_width == 2:
        data = (audio * 32768.0).clip(-32768, 32767).astype(np.int16)
        return data.tobytes()
    elif sample_width == 4:
        data = (audio * 2147483648.0).clip(-2147483648, 2147483647).astype(np.int32)
        return data.tobytes()
    else:
        raise ValueError(f"Unsupported sample width: {sample_width}")


def resample_audio(audio: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
    """
    Remuestreo de audio de alto rendimiento optimizado para baja latencia en tiempo real.
    Prioridades:
    1. Si from_rate == to_rate, retorno directo (zero-copy).
    2. scipy.signal.resample_poly: Filtro polifásico FIR en C (10-15x más rápido que resampy, ideal 24k -> 16k = 2/3).
    3. torchaudio.functional.resample: Implementación vectorizada en PyTorch.
    4. resampy: Fallback con interpolación sinc.
    5. np.interp: Fallback lineal de emergencia.
    """
    if from_rate == to_rate or len(audio) == 0:
        return audio

    global _resample_poly_available, _torchaudio_available

    # 1. scipy.signal.resample_poly (ultra rápido para razones racionales como 24k -> 16k = 2/3)
    if _resample_poly_available is not False:
        try:
            from scipy.signal import resample_poly
            _resample_poly_available = True
            gcd = math.gcd(from_rate, to_rate)
            up = to_rate // gcd
            down = from_rate // gcd
            return resample_poly(audio, up, down).astype(np.float32)
        except Exception:
            _resample_poly_available = False

    # 2. torchaudio.functional.resample
    if _torchaudio_available is not False:
        try:
            import torch
            import torchaudio.functional as AF
            _torchaudio_available = True
            t_audio = torch.from_numpy(audio) if isinstance(audio, np.ndarray) else audio
            if t_audio.ndim == 1:
                t_audio = t_audio.unsqueeze(0)
            resampled = AF.resample(t_audio.float(), from_rate, to_rate)
            return resampled.squeeze(0).cpu().numpy().astype(np.float32)
        except Exception:
            _torchaudio_available = False

    # 3. resampy fallback
    try:
        import resampy
        return resampy.resample(audio, from_rate, to_rate).astype(np.float32)
    except Exception:
        pass

    # 4. Interpolación lineal de emergencia
    ratio = to_rate / from_rate
    n_samples = int(len(audio) * ratio)
    indices = np.linspace(0, len(audio) - 1, n_samples)
    return np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)


# Alias para máxima claridad y compatibilidad
fast_resample = resample_audio
