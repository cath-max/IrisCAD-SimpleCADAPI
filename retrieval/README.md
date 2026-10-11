# API retrieval

The retriever selects a set of SimpleCADAPI documents for each CAD request, so the coding model receives relevant API references instead of the entire catalog of 165 API's.

## Basic logic

```text
user request
  -> BM25 keyword score + (optional) embedding similarity
  -> always keep the fixed core APIs
  -> add closely related producer APIs needed by a selected operation
  -> return a relevance-ordered Top-20 document slice
```

- With an embedding key and `embeddings.npy`, retrieval is hybrid (vector + BM25). Without them, only BM25 is used.
- The core APIs are always retained.
- Related expansion can add a small number of high-confidence companion APIs, such as a sweep path/profile for a selected sweep operation. It is local deterministic scoring without extra LLM call or embedding request.
- The final result contains exactly 20 APIs when the catalog has at least 20.
- `hit_ids` and `reasons` have matching order. A reason beginning with `related:` means the API was added as a companion to another selected API.

## Example

For this request:

```text
Create a smooth bent tube with a round opening, following a curved path.
```

The slice should contain the main operation `sweep_rsolid`, plus relevant APIs such as `make_spline_rwire` and `make_circle_rface`, which serves as producer API's that return the input parameters path/profile for `sweep_rsolid`.

## Build and run

After changing API docs, rebuild the catalog and embeddings:

```bash
python scripts/build_api_catalog.py
python scripts/build_api_retrieval_index.py
```

Start the HTTP sidecar for CADAM:

```bash
python scripts/serve_api_retrieval.py --host 127.0.0.1 --port 8765
```

The warm sidecar does not reload changed files, so restart it after changing
retrieval Python code, the catalog, or embeddings.

For a quick local check:

```bash
python scripts/retrieve_apis.py "Create a smooth bent tube with a round opening"
```

## IrisCAD Cloud Run deployment

The production sidecar is deployed as the private `iriscad-retrieval` Cloud
Run service. Its checked-in `embeddings.npy` must stay row-aligned with
`catalog.jsonl`; `/health` reports both `embeddings_loaded` and whether vector
retrieval is enabled by default.

From a Google Cloud Shell clone of this repository, run:

```bash
bash scripts/bootstrap_retrieval_cloud.sh
```

The script creates/updates the embedding API key secret without echoing the
key, deploys the private service with one warm minimum instance, grants the
IrisCAD runtime identity `run.invoker`, and prints the URL to set as the
`_API_RETRIEVAL_URL` substitution on the `iriscad-web` Cloud Build trigger.
