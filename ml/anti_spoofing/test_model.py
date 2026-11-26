
from pathlib import Path
import onnxruntime as ort

MODEL_PATH = Path(__file__).parent / "weights" / "MiniFASNetV2.onnx"

print("Checking model file...")

if not MODEL_PATH.exists():
    print("ERROR: Model file not found!")
    raise SystemExit(1)

print("Model size:", round(MODEL_PATH.stat().st_size / (1024 * 1024), 2), "MB")

try:
    session = ort.InferenceSession(
        str(MODEL_PATH),
        providers=["CPUExecutionProvider"]
    )

    print("\nMODEL LOADED SUCCESSFULLY!")
    print("Input details:")

    for item in session.get_inputs():
        print("Name:", item.name)
        print("Shape:", item.shape)
        print("Type:", item.type)

    print("\nOutput details:")

    for item in session.get_outputs():
        print("Name:", item.name)
        print("Shape:", item.shape)
        print("Type:", item.type)

except Exception as error:
    print("\nMODEL LOADING FAILED!")
    print(error)
