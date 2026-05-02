#!/usr/bin/env python3
"""Download and patch Salesforce/codet5p-110m-embedding model for compatibility."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Set cache directory and HF token for authenticated requests
os.environ['HF_HOME'] = os.path.expanduser('~/.cache/huggingface')

# Get HF token from environment (loaded from .env file)
hf_token = os.getenv('HF_TOKEN')
if not hf_token:
    raise ValueError(
        "HF_TOKEN not found. Please set it in your .env file. "
        "Copy .env.example to .env and add your HuggingFace token."
    )
os.environ['HF_TOKEN'] = hf_token

import torch
from transformers import AutoConfig, AutoModel, AutoTokenizer

model_name = "Salesforce/codet5p-110m-embedding"
print(f"Downloading and patching {model_name}...")

# Step 1: Download tokenizer (this works fine)
print("Downloading tokenizer...")
tokenizer = AutoTokenizer.from_pretrained(
    model_name, trust_remote_code=True, token=os.environ['HF_TOKEN']
)
print("✓ Tokenizer downloaded")

# Step 2: Load config and patch it
print("Downloading config...")
config = AutoConfig.from_pretrained(
    model_name, trust_remote_code=True, token=os.environ['HF_TOKEN']
)

# Patch missing attributes for newer transformers versions
if not hasattr(config, 'is_decoder'):
    print("Patching config: adding is_decoder=False")
    config.is_decoder = False
    
if not hasattr(config, 'is_encoder_decoder'):
    print("Patching config: adding is_encoder_decoder=False")
    config.is_encoder_decoder = False

# Additional patches for T5 compatibility
if hasattr(config, 'decoder'):
    if not hasattr(config.decoder, 'is_decoder'):
        config.decoder.is_decoder = False

print("✓ Config patched")

# Step 3: Load model with patched config
print("Downloading model (this may take a few minutes)...")
try:
    model = AutoModel.from_pretrained(
        model_name,
        config=config,
        trust_remote_code=True,
        token=os.environ['HF_TOKEN']
    )
    print("✓ Model downloaded successfully")
    
    # Test the model
    print("\nTesting model...")
    test_input = tokenizer("def hello(): pass", return_tensors="pt")
    with torch.no_grad():
        output = model(**test_input)
    # Handle different output formats
    if hasattr(output, 'last_hidden_state'):
        print(f"✓ Model works! Output shape: {output.last_hidden_state.shape}")
    elif hasattr(output, 'pooler_output'):
        print(f"✓ Model works! Output shape: {output.pooler_output.shape}")
    elif isinstance(output, torch.Tensor):
        print(f"✓ Model works! Output shape: {output.shape}")
    else:
        print(f"✓ Model works! Output type: {type(output)}")
    
except Exception as e:
    print(f"✗ Error loading model: {e}")
    raise

print("\n" + "="*60)
print("SUCCESS! Model is ready to use.")
print("="*60)
print("\nYou can now use the HuggingFace embedding provider:")
print(f'  python main.py --repo-path /path/to/repo --embedding-provider huggingface')
