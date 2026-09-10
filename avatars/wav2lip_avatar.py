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
def warm_up(batch_size, model, modelres, use_fp16=True):
    # 预热函数
    logger.info('warmup model...')
    img_batch = torch.ones(batch_size, 6, modelres, modelres).to(device)
    mel_batch = torch.ones(batch_size, 1, 80, 16).to(device)
    if use_fp16 and device == 'cuda':
        with torch.cuda.amp.autocast(dtype=torch.float16):
            model(mel_batch, img_batch)
    else:
        model(mel_batch, img_batch)

@register("avatar", "wav2lip")
class LipReal(BaseAvatar):
    @torch.no_grad()
    def __init__(self, opt, model, avatar):
        super().__init__(opt)

        self.model = model
        # Resolución esperada por el modelo (wav2lip256.pth → 256, wav2lip.pth → 96)
        self.modelres = getattr(opt, 'modelres', 256)
        # Habilitar inferencia FP16 con autocast si estamos en GPU CUDA
        self.use_fp16 = getattr(opt, 'fp16', True) and (device == 'cuda')

        self.frame_list_cycle, self.face_list_cycle, self.coord_list_cycle = avatar

        # 1. Pre-redimensionar caras al tamaño esperado por el modelo una sola vez al inicializar
        #    Elimina cv2.resize en el bucle de inferencia en tiempo real
        if self.face_list_cycle:
            self.face_list_cycle = [
                cv2.resize(face, (self.modelres, self.modelres))
                if (face.shape[0] != self.modelres or face.shape[1] != self.modelres)
                else face
                for face in self.face_list_cycle
            ]

        # 2. Pre-computar tensores de 6 canales (enmascarado + original) normalizados en GPU/device
        #    Elimina alocaciones de numpy, concatenaciones y transferencias PCIe CPU->GPU por batch
        self.precomputed_faces = None
        self._precompute_face_tensors()

        self.asr = MelASR(opt, self)
        self.asr.warm_up()

    def _precompute_face_tensors(self):
        if not self.face_list_cycle:
            return
        logger.info(f"Pre-computando tensores faciales para {len(self.face_list_cycle)} frames (FP16={self.use_fp16}, device={device})...")
        tensors = []
        half_res = self.modelres // 2
        for face in self.face_list_cycle:
            masked_face = face.copy()
            masked_face[half_res:] = 0
            concat_face = np.concatenate((masked_face, face), axis=2).astype(np.float32) / 255.0
            transposed = np.transpose(concat_face, (2, 0, 1))  # (6, modelres, modelres)
            tensors.append(torch.from_numpy(transposed))

        self.precomputed_faces = torch.stack(tensors).to(device)
        logger.info(f"Tensores faciales residentes en {device}: forma {self.precomputed_faces.shape}")

    def inference_batch(self, index, audiofeat_batch):
        # 这里的 index 是针对当前 avatar 的索引
        # 返回一个 batch 的推理结果，batch 大小由 self.batch_size 决定
        length = len(self.face_list_cycle)

        # 1. Obtención de batch de caras: indexación GPU directa sin copias en memoria
        if self.precomputed_faces is not None:
            indices = [mirror_index(length, index + i) for i in range(self.batch_size)]
            img_batch = self.precomputed_faces[indices]
        else:
            img_batch = []
            for i in range(self.batch_size):
                idx = mirror_index(length, index + i)
                face = self.face_list_cycle[idx]
                img_batch.append(face)
            img_batch = np.asarray(img_batch)
            img_masked = img_batch.copy()
            img_masked[:, self.modelres//2:] = 0
            img_batch = np.concatenate((img_masked, img_batch), axis=3) / 255.
            img_batch = torch.FloatTensor(np.transpose(img_batch, (0, 3, 1, 2))).to(device)

        # 2. Audio features a tensor [B, 1, 80, 16] directamente en device
        audiofeat_batch = torch.from_numpy(np.asarray(audiofeat_batch)).unsqueeze(1).float().to(device)

        # 3. Inferencia con FP16 (autocast) para aprovechar Tensor Cores en GPUs NVIDIA / Jetson Orin
        with torch.no_grad():
            if self.use_fp16 and device == 'cuda':
                with torch.cuda.amp.autocast(dtype=torch.float16):
                    pred = self.model(audiofeat_batch, img_batch)
            else:
                pred = self.model(audiofeat_batch, img_batch)

        # 4. Transposición, escalado y conversión a uint8 directamente en CUDA
        #    Reduce 4x el ancho de banda transferido de GPU a CPU (uint8 vs float32)
        pred = (pred.permute(0, 2, 3, 1) * 255.0).clamp(0, 255).to(torch.uint8).cpu().numpy()
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

