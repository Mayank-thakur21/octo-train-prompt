import sys
import json
import re
from pathlib import Path
import pandas as pd
import torch
from PIL import Image
from transformers import AutoProcessor, LlavaForConditionalGeneration
import os

def main():
    if len(sys.argv) < 3:
        print("Usage: python3 solution.py <public_dir> <submission_out>")
        sys.exit(1)

    public_dir = Path(sys.argv[1])
    submission_out = Path(sys.argv[2])

    train_path = public_dir / "train.csv"
    test_path = public_dir / "test.csv"

    train_df = pd.read_csv(train_path)
    test_df = pd.read_csv(test_path)

    # Calculate fallback values exclusively from train
    fallback_count = int(train_df["corrected_count"].median()) if "corrected_count" in train_df.columns else 5
    fallback_detector = 1
    if "detector_correct" in train_df.columns:
        fallback_detector = int(train_df["detector_correct"].mode()[0])

    # Load model
    # To run offline in Kaggle, participants typically mount datasets.
    # We will check common local dataset paths, then fallback to HF hub ID.
    possible_model_paths = [
        "/kaggle/input/llava-1.5-7b-hf",
        "/kaggle/input/llava-hf/transformers/llava-1.5-7b-hf/1",
        "llava-hf/llava-1.5-7b-hf"
    ]

    model_id = possible_model_paths[-1]
    for path in possible_model_paths[:-1]:
        if Path(path).exists():
            model_id = path
            break

    try:
        processor = AutoProcessor.from_pretrained(model_id)
        model = LlavaForConditionalGeneration.from_pretrained(
            model_id,
            torch_dtype=torch.float16,
            low_cpu_mem_usage=True,
            device_map="auto"
        )
    except Exception as e:
        print(f"Failed to load model from {model_id}: {e}")
        # Setup fallback if model loading fails completely in test
        model = None
        processor = None

    results = []

    for _, row in test_df.iterrows():
        row_id = row["id"]

        # Default fallback
        prediction = {
            "id": row_id,
            "corrected_count": fallback_count,
            "remove_ids": "[]",
            "add_points": "[]",
            "detector_correct": fallback_detector
        }

        try:
            clean_img_path = public_dir / row["clean_image"]
            proposal_img_path = public_dir / row["proposal_image"]

            clean_img = Image.open(clean_img_path).convert("RGB")
            proposal_img = Image.open(proposal_img_path).convert("RGB")

            # Stitch horizontally
            w1, h1 = clean_img.size
            w2, h2 = proposal_img.size
            stitched = Image.new("RGB", (w1 + w2, max(h1, h2)))
            stitched.paste(clean_img, (0, 0))
            stitched.paste(proposal_img, (w1, 0))

            candidates_raw = row["candidates"]
            detector_box = row["detector_box"]

            candidates_list = json.loads(candidates_raw) if isinstance(candidates_raw, str) else candidates_raw
            valid_candidate_ids = set()
            if isinstance(candidates_list, list):
                for c in candidates_list:
                    if isinstance(c, dict) and "id" in c:
                        valid_candidate_ids.add(int(c["id"]))

            prompt = f"USER: <image>\nAnalyze the two images. The left is a clean microscopy image. The right is the same image with numbered candidate cell marks and a cyan detector box. \nCandidates: {candidates_raw}\nDetector box: {detector_box}\n\nProvide your analysis as a JSON object with the following keys:\n'remove_ids': list of candidate IDs to remove (unsupported marks)\n'add_points': list of objects with 'x' and 'y' coordinates for missing cells\n'corrected_count': total correct cell count\n'detector_correct': 1 if the detector box claimed_count is correct, else 0.\n\nOnly output valid JSON.\nASSISTANT:"

            if model is not None and processor is not None:
                inputs = processor(text=prompt, images=stitched, return_tensors="pt")
                # Move to the correct device
                inputs = {k: v.to(model.device) for k, v in inputs.items()}

                # Generate
                output = model.generate(**inputs, max_new_tokens=256, do_sample=False)
                response = processor.decode(output[0][inputs["input_ids"].shape[-1]:], skip_special_tokens=True)

                # Parse JSON
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    try:
                        parsed = json.loads(json_match.group(0))

                        raw_remove_ids = parsed.get("remove_ids", [])
                        add_points = parsed.get("add_points", [])
                        detector_correct = parsed.get("detector_correct", fallback_detector)

                        # Validate remove_ids
                        if not isinstance(raw_remove_ids, list):
                            raw_remove_ids = []

                        clean_remove_ids = []
                        for rid in raw_remove_ids:
                            try:
                                rid_int = int(rid)
                                if rid_int in valid_candidate_ids:
                                    clean_remove_ids.append(rid_int)
                            except (ValueError, TypeError):
                                pass
                        # Ensure uniqueness
                        clean_remove_ids = list(set(clean_remove_ids))

                        # Validate add_points
                        if not isinstance(add_points, list):
                            add_points = []

                        detector_correct = 1 if detector_correct in [1, "1"] else 0

                        # clamp added points
                        valid_add_points = []
                        for pt in add_points:
                            if isinstance(pt, dict) and 'x' in pt and 'y' in pt:
                                try:
                                    x = max(0.0, min(511.9, float(pt['x'])))
                                    y = max(0.0, min(511.9, float(pt['y'])))
                                    valid_add_points.append({"x": x, "y": y})
                                except (ValueError, TypeError):
                                    pass

                        # Calculate correct count based on retained candidates + added points
                        retained = len(valid_candidate_ids) - len(clean_remove_ids)
                        corrected_count = retained + len(valid_add_points)

                        prediction.update({
                            "corrected_count": corrected_count,
                            "remove_ids": json.dumps(clean_remove_ids),
                            "add_points": json.dumps(valid_add_points),
                            "detector_correct": detector_correct
                        })
                    except Exception as parse_e:
                        print(f"JSON Parse error for {row_id}: {parse_e}")

        except Exception as e:
            print(f"Error processing {row_id}: {e}")

        results.append(prediction)

    submission_df = pd.DataFrame(results)
    submission_out.parent.mkdir(parents=True, exist_ok=True)
    submission_df.to_csv(submission_out, index=False, columns=["id", "corrected_count", "remove_ids", "add_points", "detector_correct"])

if __name__ == "__main__":
    main()
