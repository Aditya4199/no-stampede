import re
import glob

for file in glob.glob('tests/*.py'):
    with open(file, 'r') as f:
        content = f.read()
    
    new_content = re.sub(
        r'("Authorization": f"Bearer \{[^}]+\}")(?!, "Idempotency)',
        r'\1, "Idempotency-Key": str(uuid.uuid4())',
        content
    )
    if new_content != content:
        if 'import uuid' not in new_content:
            new_content = 'import uuid\n' + new_content
        with open(file, 'w') as f:
            f.write(new_content)
        print(f"Updated {file}")
