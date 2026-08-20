# Troubleshooting

## HuggingFace Model Not Found

```
ERROR: Failed to load model 'nomic-ai/nomic-embed-code'.
```

**Solution**:
```bash
# Ensure HF_TOKEN is set in .env, then download the model:
cvg-download-model              # Nomic (default)
cvg-download-model --model jina # Jina
```

## Dimension Mismatch

If you see a dimension mismatch error during queries, you may have indexed with one model but are querying with another. Re-index your repository with the correct model:

```bash
cvg-ingest --repo-path /path/to/repo --model nomic --verbose
# or
cvg-ingest --repo-path /path/to/repo --model jina --verbose
```

## OpenAI API Key Not Set

```
ERROR: OPENAI_API_KEY environment variable is required.
```

**Solution**:
```bash
export OPENAI_API_KEY='your-key'
# Or add to your .env file
```

## Qdrant Connection Error

```
ERROR: Cannot connect to Qdrant server.
```

**Solution**:
```bash
docker-compose up -d
curl http://localhost:6333/healthz
```

## Neo4j Connection Error

Neo4j is optional — the pipeline continues without it if unavailable, or use `--no-graph` to skip entirely.

```bash
docker-compose ps neo4j
docker-compose logs neo4j
```

## Memory Issues

For large repositories, reduce batch size:

```bash
cvg-ingest --repo-path /large/repo --batch-size 32
```

