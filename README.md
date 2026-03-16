# Scibot
A multi-agent multi-modal RAG application for scientific users looking for a tool to assisst them in intensive study scenarios and research.
## Quick start


## Key Features and tools
### Rich data store and accessibility
- Fetch data from multiple sources such as arxiv, PubMed, pdfs, latex, markdown, images, audios, videos, youtube, github, webpages or websites. 
- Add live data sources such as Postgres, MongoDB, CSVs or JSONs, use them for analysis and get insights from them, to aid in the research.
- Separate data collection for each chat to avoid data pollution and ensure relevance of the retrieved data.
- Smart indexing and data retrieval strategies to ensure accuracy at lower costs. 
- Per chat configuration for granular control over model usage.
- Use your data collections or all of your data as MCP context in other tools for more accessibility.

## Key design choices

## Remarks on key decisions

## Future Scopes

## API and frontend design

The production container builds the frontend during the image build and serves the compiled app from `/`.
The FastAPI API remains available under `/api`, with MCP routes under `/mcp`.
