import json
import re
from pathlib import Path

class FeatureDetector:
    def __init__(self, manifest_path):
        with open(manifest_path, 'r', encoding='utf-8') as f:
            self.manifest = json.load(f)

    def detect(self, source_path, schema=None):
        results = []
        source_path = Path(source_path)
        
        for feature in self.manifest:
            trigger = feature.get('trigger', {})
            t_type = trigger.get('type')
            
            supported = False
            reason = ""

            if t_type == "always":
                supported = True
                reason = "Core feature"
            
            elif t_type == "field_check":
                pattern = trigger.get('pattern')
                if schema and any(re.match(pattern, f, re.I) for f in schema):
                    supported = True
                    reason = f"Detected matching field in schema"
            
            elif t_type == "source_pattern":
                pattern = trigger.get('pattern')
                # Simple check for files in source path
                if any(re.match(pattern, p.name) for p in source_path.rglob("*")):
                    supported = True
                    reason = f"Source files match pattern: {pattern}"

            results.append({
                "id": feature['id'],
                "label": feature['label'],
                "status": "supported" if supported else "available",
                "reason": reason,
                "cli": feature.get('cli_integration', {})
            })
            
        return results

if __name__ == "__main__":
    # Test stub
    detector = FeatureDetector("factory/references/features-manifest.json")
    # Simulate detection
    mock_schema = ["id", "term", "rank", "freq"]
    matches = detector.detect("sources/lexicon", mock_schema)
    print(json.dumps(matches, indent=2, ensure_ascii=False))
