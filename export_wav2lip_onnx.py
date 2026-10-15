#!/usr/bin/env python3
"""
Script de exportación de Wav2Lip (.pth) a ONNX (.onnx)
Permite generar el modelo intermedio para luego compilarlo a TensorRT en NVIDIA Jetson Orin NX.
"""

import os
import sys
import argparse
import torch

# Asegurar que el directorio raíz del proyecto esté en el PYTHONPATH
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from avatars.wav2lip.models.wav2lip_v2 import Wav2Lip


def parse_args():
    parser = argparse.ArgumentParser(description="Exportar modelo Wav2Lip de PyTorch (.pth) a ONNX")
    parser.add_argument(
        "--checkpoint",
        type=str,
        default="./models/wav2lip256.pth",
        help="Ruta al checkpoint de PyTorch (.pth)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="./models/wav2lip256.onnx",
        help="Ruta donde se guardará el modelo exportado (.onnx)",
    )
    parser.add_argument(
        "--modelres",
        type=int,
        default=256,
        help="Resolución de la cara (256 para wav2lip256, 96 para wav2lip clásico)",
    )
    parser.add_argument(
        "--batch_size",
        type=int,
        default=8,
        help="Batch size usado durante el trace inicial",
    )
    parser.add_argument(
        "--static",
        action="store_true",
        default=False,
        help="Exportar con batch fijo (por defecto se exporta con Dynamic Batch)",
    )
    parser.add_argument(
        "--opset",
        type=int,
        default=14,
        help="Versión de ONNX opset (14 o 17 son recomendadas para TensorRT)",
    )
    return parser.parse_args()


def export_onnx(checkpoint_path, output_path, modelres=256, batch_size=8, dynamic=True, opset=14):
    print(f"📦 Cargando checkpoint: {checkpoint_path}")
    if not os.path.exists(checkpoint_path):
        raise FileNotFoundError(f"No se encontró el checkpoint: {checkpoint_path}")

    # 1. Instanciar modelo
    model = Wav2Lip()
    checkpoint = torch.load(checkpoint_path, map_location="cpu")
    s = checkpoint["state_dict"] if "state_dict" in checkpoint else checkpoint
    new_s = {}
    for k, v in s.items():
        new_s[k.replace("module.", "")] = v
    model.load_state_dict(new_s)
    model.eval()
    print("✅ Pesos cargados correctamente en el modelo PyTorch.")

    # 2. Crear tensores dummy de entrada
    # audio_sequences: [B, 1, 80, 16]
    # face_sequences:  [B, 6, modelres, modelres]
    dummy_audio = torch.randn(batch_size, 1, 80, 16, dtype=torch.float32)
    dummy_face = torch.randn(batch_size, 6, modelres, modelres, dtype=torch.float32)

    # 3. Test de inferencia PyTorch
    print("🧪 Verificando inferencia con PyTorch en CPU...")
    with torch.no_grad():
        test_out = model(dummy_audio, dummy_face)
    print(f"✅ Inferencia de prueba exitosa! Salida: {test_out.shape}")

    # 4. Configurar ejes dinámicos para soportar cualquier batch size en tiempo de ejecución
    input_names = ["audio_sequences", "face_sequences"]
    output_names = ["output"]

    dynamic_axes = None
    if dynamic:
        dynamic_axes = {
            "audio_sequences": {0: "batch_size"},
            "face_sequences": {0: "batch_size"},
            "output": {0: "batch_size"},
        }
        print("⚡ Modo Dynamic Batch activado (soporta batches variables 1..16).")
    else:
        print(f"🔒 Modo Static Batch fijado a {batch_size}.")

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    # 5. Exportar a ONNX
    print(f"🚀 Exportando a ONNX: {output_path} (Opset {opset})...")
    torch.onnx.export(
        model,
        (dummy_audio, dummy_face),
        output_path,
        export_params=True,
        opset_version=opset,
        do_constant_folding=True,
        input_names=input_names,
        output_names=output_names,
        dynamic_axes=dynamic_axes,
    )
    print(f"🎉 Modelo ONNX generado exitosamente en: {output_path}")

    # 6. Validar ONNX si la librería onnx está disponible
    try:
        import onnx

        onnx_model = onnx.load(output_path)
        onnx.checker.check_model(onnx_model)
        print("✅ Verificación del grafo ONNX completada sin errores.")
    except ImportError:
        print("ℹ️ Paquete 'onnx' no instalado; omitiendo validación estática del grafo.")
    except Exception as e:
        print(f"⚠️ Advertencia al verificar ONNX: {e}")

    # 7. Mostrar comando exacto para compilar en Jetson
    engine_path = output_path.rsplit(".", 1)[0] + ".engine"
    print("\n" + "=" * 80)
    print("📋 COMANDO RECOMENDADO PARA COMPILAR EN NVIDIA JETSON ORIN NX (trtexec):")
    print("=" * 80)
    if dynamic:
        cmd = (
            f"/usr/src/tensorrt/bin/trtexec \\\n"
            f"  --onnx={output_path} \\\n"
            f"  --saveEngine={engine_path} \\\n"
            f"  --fp16 \\\n"
            f"  --minShapes=audio_sequences:1x1x80x16,face_sequences:1x6x{modelres}x{modelres} \\\n"
            f"  --optShapes=audio_sequences:8x1x80x16,face_sequences:8x6x{modelres}x{modelres} \\\n"
            f"  --maxShapes=audio_sequences:16x1x80x16,face_sequences:16x6x{modelres}x{modelres}"
        )
    else:
        cmd = (
            f"/usr/src/tensorrt/bin/trtexec \\\n"
            f"  --onnx={output_path} \\\n"
            f"  --saveEngine={engine_path} \\\n"
            f"  --fp16"
        )
    print(cmd)
    print("=" * 80 + "\n")


if __name__ == "__main__":
    args = parse_args()
    export_onnx(
        checkpoint_path=args.checkpoint,
        output_path=args.output,
        modelres=args.modelres,
        batch_size=args.batch_size,
        dynamic=not args.static,
        opset=args.opset,
    )
