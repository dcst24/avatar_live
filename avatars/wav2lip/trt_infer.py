import os
import torch
from utils.logger import logger

try:
    import tensorrt as trt
    TRT_AVAILABLE = True
except ImportError:
    TRT_AVAILABLE = False
    trt = None


class TrtWav2Lip:
    """
    Wrapper de inferencia TensorRT para Wav2Lip con soporte para:
    - JetPack 5 (TensorRT 8.5 / execute_async_v2)
    - JetPack 6 (TensorRT 8.6+ / 10.x / execute_async_v3)
    - Vinculación directa con tensores PyTorch en CUDA (zero-copy vía data_ptr())
    - Dynamic Batching (soporta cualquier batch_size configurado en LiveTalking)
    """

    def __init__(self, engine_path: str, modelres: int = 256):
        if not TRT_AVAILABLE:
            raise ImportError(
                "El paquete 'tensorrt' no está instalado en este entorno de Python.\n"
                "Para usar TensorRT en la Jetson Orin, asegúrate de tener instalado JetPack "
                "y los bindings de Python (ej: sudo apt-get install python3-libnvinfer)."
            )

        if not os.path.exists(engine_path):
            raise FileNotFoundError(f"No se encontró el archivo de motor TensorRT: {engine_path}")

        self.engine_path = engine_path
        self.modelres = modelres
        self.trt_logger = trt.Logger(trt.Logger.WARNING)

        logger.info(f"Cargando motor TensorRT desde: {engine_path}")
        with open(engine_path, "rb") as f, trt.Runtime(self.trt_logger) as runtime:
            self.engine = runtime.deserialize_cuda_engine(f.read())

        if self.engine is None:
            raise RuntimeError(f"Error al deserializar el motor TensorRT: {engine_path}")

        self.context = self.engine.create_execution_context()
        if self.context is None:
            raise RuntimeError("Error al crear el contexto de ejecución de TensorRT.")

        # Detectar versión de API (TRT 8.6+ / 10.x vs TRT 8.5)
        self.is_v3_api = hasattr(self.context, "execute_async_v3")

        self.audio_name = None
        self.face_name = None
        self.output_name = None

        self.audio_binding_idx = None
        self.face_binding_idx = None
        self.output_binding_idx = None

        self._discover_io()
        logger.info(
            f"TensorRT Engine listo (API {'v3' if self.is_v3_api else 'v2'}). "
            f"Audio: '{self.audio_name}', Face: '{self.face_name}', Output: '{self.output_name}'"
        )

    def _discover_io(self):
        """Identifica los nombres e índices de los tensores de entrada y salida."""
        if hasattr(self.engine, "num_io_tensors"):
            # API moderna (TensorRT 8.6 / 10.x)
            for i in range(self.engine.num_io_tensors):
                name = self.engine.get_tensor_name(i)
                mode = self.engine.get_tensor_mode(name)
                shape = self.engine.get_tensor_shape(name)
                if mode == trt.TensorIOMode.INPUT:
                    if "audio" in name.lower() or (len(shape) == 4 and (shape[1] == 1 or shape[2] == 80)):
                        self.audio_name = name
                    else:
                        self.face_name = name
                else:
                    self.output_name = name
        else:
            # API legacy (TensorRT 8.5 en JetPack 5)
            for i in range(self.engine.num_bindings):
                name = self.engine.get_binding_name(i)
                is_input = self.engine.binding_is_input(i)
                shape = self.engine.get_binding_shape(i)
                if is_input:
                    if "audio" in name.lower() or (len(shape) == 4 and (shape[1] == 1 or shape[2] == 80)):
                        self.audio_name = name
                        self.audio_binding_idx = i
                    else:
                        self.face_name = name
                        self.face_binding_idx = i
                else:
                    self.output_name = name
                    self.output_binding_idx = i

        if not self.audio_name:
            self.audio_name = "audio_sequences"
        if not self.face_name:
            self.face_name = "face_sequences"
        if not self.output_name:
            self.output_name = "output"

    def eval(self):
        """Compatibilidad con la interfaz de PyTorch model.eval()"""
        return self

    def to(self, *args, **kwargs):
        """Compatibilidad con la interfaz de PyTorch model.to(device)"""
        return self

    def __call__(self, audio_sequences: torch.Tensor, face_sequences: torch.Tensor) -> torch.Tensor:
        return self.forward(audio_sequences, face_sequences)

    def forward(self, audio_sequences: torch.Tensor, face_sequences: torch.Tensor) -> torch.Tensor:
        """
        Ejecuta la inferencia en GPU mediante TensorRT.
        audio_sequences: Tensor GPU float32 [B, 1, 80, 16]
        face_sequences:  Tensor GPU float32 [B, 6, H, W]
        Retorna:
        output:          Tensor GPU float32 [B, 3, H, W]
        """
        batch_size = audio_sequences.shape[0]
        device = face_sequences.device
        current_stream = torch.cuda.current_stream().cuda_stream

        # Asegurar tensores contiguos en memoria GPU
        if not audio_sequences.is_contiguous():
            audio_sequences = audio_sequences.contiguous()
        if not face_sequences.is_contiguous():
            face_sequences = face_sequences.contiguous()

        # Determinar resolución del tensor de caras
        h = face_sequences.shape[2]
        w = face_sequences.shape[3]

        # Reservar tensor de salida directamente en memoria GPU
        out_tensor = torch.empty(
            (batch_size, 3, h, w),
            dtype=torch.float32,
            device=device
        )

        if self.is_v3_api:
            # TensorRT 8.6+ / 10.x API
            self.context.set_input_shape(self.audio_name, tuple(audio_sequences.shape))
            self.context.set_input_shape(self.face_name, tuple(face_sequences.shape))

            self.context.set_tensor_address(self.audio_name, audio_sequences.data_ptr())
            self.context.set_tensor_address(self.face_name, face_sequences.data_ptr())
            self.context.set_tensor_address(self.output_name, out_tensor.data_ptr())

            self.context.execute_async_v3(stream_handle=current_stream)
        else:
            # TensorRT 8.5 Legacy API
            if self.audio_binding_idx is None:
                self.audio_binding_idx = self.engine.get_binding_index(self.audio_name)
                self.face_binding_idx = self.engine.get_binding_index(self.face_name)
                self.output_binding_idx = self.engine.get_binding_index(self.output_name)

            self.context.set_binding_shape(self.audio_binding_idx, tuple(audio_sequences.shape))
            self.context.set_binding_shape(self.face_binding_idx, tuple(face_sequences.shape))

            bindings = [0] * self.engine.num_bindings
            bindings[self.audio_binding_idx] = audio_sequences.data_ptr()
            bindings[self.face_binding_idx] = face_sequences.data_ptr()
            bindings[self.output_binding_idx] = out_tensor.data_ptr()

            self.context.execute_async_v2(bindings=bindings, stream_handle=current_stream)

        return out_tensor
