import soundfile as sf
import numpy as np
from utils.audio import resample_audio

def read_audio_file(file_path):
    # 使用soundfile库的read函数读取音频文件
    audio, sample_rate = sf.read(file_path)
    return audio, sample_rate

def change_sample_rate(audio, current_rate, target_rate):
    # Usar resample_audio acelerado
    new_audio = resample_audio(audio, current_rate, target_rate)
    return new_audio, target_rate

def change_channels(audio, current_channels, target_channels):
    # 使用numpy库的reshape函数改变通道数
    new_audio = audio.reshape(-1, current_channels)
    new_audio = np.tile(new_audio, (1, target_channels // current_channels))
    return new_audio, target_channels

def change_bit_depth(audio, current_depth, target_depth):
    # 使用numpy库的astype函数改变位长
    new_audio = audio.astype(np.int16)
    new_audio *= 2 ** (target_depth - current_depth)
    return new_audio, target_depth

def save_audio_file(audio, sample_rate, file_path):
    # 使用soundfile库的write函数保存音频文件
    sf.write(file_path, audio, sample_rate)