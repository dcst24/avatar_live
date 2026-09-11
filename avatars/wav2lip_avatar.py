###############################################################################
#  Copyright (C) 2024 LiveTalking@lipku https://github.com/lipku/LiveTalking
#  email: lipku@foxmail.com
# 
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#  
#       http://www.apache.org/licenses/LICENSE-2.0
# 
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
###############################################################################
#
#  Wav2Lip 数字人 — 迁移自 lipreal.py + lipasr.py
#

import math
import torch
import numpy as np

import os
import time
import cv2
import glob
import pickle
import copy

import queue
from queue import Queue
from threading import Thread, Event
import torch.multiprocessing as mp

from avatars.audio_features.mel import MelASR
import asyncio
from av import AudioFrame, VideoFrame
from avatars.wav2lip.models import Wav2Lip
from avatars.base_avatar import BaseAvatar

from tqdm import tqdm
from utils.logger import logger
from utils.image import read_imgs, mirror_index
from utils.device import initialize_device
from registry import register

device = initialize_device()
logger.info('Using {} for inference.'.format(device))

def _load(checkpoint_path):
    if device == 'cuda':
        checkpoint = torch.load(checkpoint_path)
    else:
        checkpoint = torch.load(checkpoint_path,
                                map_location=lambda storage, loc: storage)
    return checkpoint

def load_model(path):
    model = Wav2Lip()
    logger.info("Load checkpoint from: {}".format(path))
    checkpoint = _load(path)
    s = checkpoint["state_dict"]
    new_s = {}
    for k, v in s.items():
        new_s[k.replace('module.', '')] = v
    model.load_state_dict(new_s)

    model = model.to(device)
    return model.eval()

def load_avatar(avatar_id):
    avatar_path = f"./data/avatars/{avatar_id}"
    full_imgs_path = f"{avatar_path}/full_imgs" 
    face_imgs_path = f"{avatar_path}/face_imgs" 
    coords_path = f"{avatar_path}/coords.pkl"
    
    with open(coords_path, 'rb') as f:
        coord_list_cycle = pickle.load(f)
    frame_list_cycle = None
    input_img_list = glob.glob(os.path.join(full_imgs_path, '*.[jpJP][pnPN]*[gG]'))
    input_img_list = sorted(input_img_list, key=lambda x: int(os.path.splitext(os.path.basename(x))[0]))
    frame_list_cycle = read_imgs(input_img_list)
    input_face_list = glob.glob(os.path.join(face_imgs_path, '*.[jpJP][pnPN]*[gG]'))
    input_face_list = sorted(input_face_list, key=lambda x: int(os.path.splitext(os.path.basename(x))[0]))
    face_list_cycle = read_imgs(input_face_list)

    return frame_list_cycle,face_list_cycle,coord_list_cycle

@torch.no_grad()
def warm_up(batch_size, model, modelres):
    # 预热函数
    logger.info('warmup model...')
    img_batch = torch.ones(batch_size, 6, modelres, modelres).to(device)
    mel_batch = torch.ones(batch_size, 1, 80, 16).to(device)
    model(mel_batch, img_batch)

@register("avatar", "wav2lip")
class LipReal(BaseAvatar):
    @torch.no_grad()
    def __init__(self, opt, model, avatar):
        super().__init__(opt)

        self.model = model
        # Resolución esperada por el modelo (wav2lip256.pth → 256, wav2lip.pth → 96)
        self.modelres = getattr(opt, 'modelres', 256)

        self.frame_list_cycle, self.face_list_cycle, self.coord_list_cycle = avatar

        # 1. Pre-redimensionar y pre-computar tensores de 6 canales en CPU RAM una sola vez al inicializar
        #    Elimina cv2.resize, máscaras y concatenaciones del bucle de inferencia sin ocupar VRAM de GPU
        self.face_list_cycle_6ch = []
        if self.face_list_cycle:
            half_res = self.modelres // 2
            for face in self.face_list_cycle:
                if face.shape[0] != self.modelres or face.shape[1] != self.modelres:
                    face = cv2.resize(face, (self.modelres, self.modelres))
                masked_face = face.copy()
                masked_face[half_res:] = 0
                concat_face = np.concatenate((masked_face, face), axis=2).astype(np.float32) / 255.0
                transposed = np.transpose(concat_face, (2, 0, 1))  # (6, modelres, modelres)
                self.face_list_cycle_6ch.append(transposed)
            logger.info(f"Caras 6-ch preparadas en CPU RAM: {len(self.face_list_cycle_6ch)} frames")

        self.asr = MelASR(opt, self)
        self.asr.warm_up()

    def inference_batch(self, index, audiofeat_batch):
        # 这里的 index 是针对当前 avatar 的索引
        # 返回一个 batch 的推理结果，batch 大小由 self.batch_size 决定
        length = len(self.face_list_cycle)
        indices = [mirror_index(length, index + i) for i in range(self.batch_size)]

        # 1. Obtener batch de caras 6 canales pre-procesadas en CPU (solo transfiere el batch actual a GPU: ~14MB)
        if self.face_list_cycle_6ch:
            img_batch_np = np.stack([self.face_list_cycle_6ch[idx] for idx in indices])
            img_batch = torch.from_numpy(img_batch_np).to(device)
        else:
            img_batch = []
            for idx in indices:
                face = self.face_list_cycle[idx]
                if face.shape[0] != self.modelres or face.shape[1] != self.modelres:
                    face = cv2.resize(face, (self.modelres, self.modelres))
                img_batch.append(face)
            img_batch = np.asarray(img_batch)
            img_masked = img_batch.copy()
            img_masked[:, self.modelres//2:] = 0
            img_batch = np.concatenate((img_masked, img_batch), axis=3) / 255.
            img_batch = torch.FloatTensor(np.transpose(img_batch, (0, 3, 1, 2))).to(device)

        # 2. Audio features a tensor [B, 1, 80, 16] directamente en device
        audiofeat_batch = torch.from_numpy(np.asarray(audiofeat_batch)).unsqueeze(1).float().to(device)

        # 3. Inferencia nativa FP32 (máxima estabilidad, sin fragmentar VRAM ni stalls cuDNN)
        with torch.no_grad():
            pred = self.model(audiofeat_batch, img_batch)

        # 4. Transferencia directa a CPU y escalado NumPy inmediato liberando la GPU
        pred = pred.cpu().numpy().transpose(0, 2, 3, 1) * 255.
        return pred

    def paste_back_frame(self, pred_frame, idx: int):
        bbox = self.coord_list_cycle[idx]
        # .copy() de NumPy es hasta 10x más rápido que copy.deepcopy() en cada frame de video
        combine_frame = self.frame_list_cycle[idx].copy()
        y1, y2, x1, x2 = bbox
        if pred_frame.dtype != np.uint8:
            pred_frame = pred_frame.astype(np.uint8)
        res_frame = cv2.resize(pred_frame, (x2 - x1, y2 - y1))
        combine_frame[y1:y2, x1:x2] = res_frame
        return combine_frame

