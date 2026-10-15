#!/usr/bin/env python3
"""
Script para compilar el modelo ONNX a motor TensorRT (.engine) directamente
desde Python en la NVIDIA Jetson Orin NX.
(Alternativa nativa a ejecutar trtexec por línea de comandos)
"""

import os
import sys
import argparse

try:
    import tensorrt as trt
except ImportError:
    print("❌ ERROR: El módulo 'tensorrt' no está instalado.")
    print("Asegúrate de ejecutar este script directamente en la NVIDIA Jetson Orin.")
    sys.exit(1)


def parse_args():
    parser = argparse.ArgumentParser(description="Compilar modelo ONNX a TensorRT Engine (.engine)")
    parser.add_argument(
        "--onnx",
        type=str,
        default="./models/wav2lip256.onnx",
        help="Ruta al archivo .onnx de entrada",
    )
    parser.add_argument(
        "--engine",
        type=str,
        default="./models/wav2lip256.engine",
        help="Ruta donde se guardará el archivo .engine generado",
    )
    parser.add_argument(
        "--fp16",
        action="store_true",
        default=True,
        help="Activar aceleración FP16 en Tensor Cores de la Jetson (recomendado)",
    )
    parser.add_argument(
        "--modelres",
        type=int,
        default=256,
        help="Resolución de la cara (256 para wav2lip256, 96 para wav2lip)",
    )
    parser.add_argument("--min_batch", type=int, default=1, help="Batch size mínimo")
    parser.add_argument("--opt_batch", type=int, default=8, help="Batch size óptimo (preferido)")
    parser.add_argument("--max_batch", type=int, default=16, help="Batch size máximo")
    parser.add_argument(
        "--workspace_gb",
        type=float,
        default=4.0,
        help="Límite de memoria de espacio de trabajo para TensorRT en GB",
    )
    return parser.parse_args()


def build_engine(
    onnx_path,
    engine_path,
    fp16=True,
    modelres=256,
    min_batch=1,
    opt_batch=8,
    max_batch=16,
    workspace_gb=4.0,
):
    print(f"🔧 Iniciando compilación de TensorRT Engine para NVIDIA Jetson Orin NX...")
    print(f"   ONNX: {onnx_path}")
    print(f"   Engine: {engine_path}")
    print(f"   Precisión: {'FP16 (Tensor Cores)' if fp16 else 'FP32'}")
    print(f"   Batch Shapes: min={min_batch}, opt={opt_batch}, max={max_batch}")

    if not os.path.exists(onnx_path):
        raise FileNotFoundError(f"No se encontró el archivo ONNX: {onnx_path}")

    logger = trt.Logger(trt.Logger.INFO)
    builder = trt.Builder(logger)
    explicit_batch = 1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH)
    network = builder.create_network(explicit_batch)
    parser = trt.OnnxParser(network, logger)

    print("📖 Parseando grafo ONNX...")
    with open(onnx_path, "rb") as f:
        if not parser.parse(f.read()):
            print("❌ Errores encontrados durante el parseo de ONNX:")
            for error in range(parser.num_errors):
                print(parser.get_error(error))
            raise RuntimeError("Fallo al parsear el modelo ONNX con TensorRT.")

    config = builder.create_builder_config()

    # Configuración de memoria de workspace
    workspace_bytes = int(workspace_gb * (1024 ** 3))
    if hasattr(config, "set_memory_pool_limit"):
        config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, workspace_bytes)
    else:
        config.max_workspace_size = workspace_bytes

    # Aceleración FP16
    if fp16 and builder.platform_has_fast_fp16:
        print("⚡ Activando flags FP16 para aprovechar los 32 Tensor Cores de la Jetson Orin NX...")
        config.set_flag(trt.BuilderFlag.FP16)
    elif fp16:
        print("⚠️ FP16 solicitado pero la plataforma no reporta soporte nativo rápido; usando fallback.")

    # Configurar perfil de optimización para Dynamic Batching
    profile = builder.create_optimization_profile()
    profile.set_shape(
        "audio_sequences",
        (min_batch, 1, 80, 16),
        (opt_batch, 1, 80, 16),
        (max_batch, 1, 80, 16),
    )
    profile.set_shape(
        "face_sequences",
        (min_batch, 6, modelres, modelres),
        (opt_batch, 6, modelres, modelres),
        (max_batch, 6, modelres, modelres),
    )
    config.add_optimization_profile(profile)

    print("⏳ Compilando y optimizando kernels CUDA (este proceso puede tardar 2-5 minutos en la Jetson)...")
    if hasattr(builder, "build_serialized_network"):
        serialized_engine = builder.build_serialized_network(network, config)
    else:
        engine = builder.build_cuda_engine(network)
        serialized_engine = engine.serialize()

    if serialized_engine is None:
        raise RuntimeError("Fallo al compilar el motor TensorRT.")

    os.makedirs(os.path.dirname(os.path.abspath(engine_path)), exist_ok=True)
    with open(engine_path, "wb") as f:
        f.write(serialized_engine)

    print(f"🎉 ¡Compilación finalizada con éxito! Motor guardado en: {engine_path}")
    size_mb = os.path.getsize(engine_path) / (1024 * 1024)
    print(f"📊 Tamaño del motor: {size_mb:.2f} MB")


if __name__ == "__main__":
    args = parse_args()
    build_engine(
        onnx_path=args.onnx,
        engine_path=args.engine,
        fp16=args.fp16,
        modelres=args.modelres,
        min_batch=args.min_batch,
        opt_batch=args.opt_batch,
        max_batch=args.max_batch,
        workspace_gb=args.workspace_gb,
    )
