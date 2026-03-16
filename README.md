# Scibot
A multi-agent multi-modal RAG application for scientific users looking for a tool to assisst them in intensive study scenarios and research.

Support for multiple data sources at minimal costs, ingestions and agents run separately in background workers, to ensure low congestion on the API server, and better process management.

<!-- SCREENSHOTS -->
![](screenshots/Screenshot%202026-03-16%20121702.png)
[More Screenshots here](screenshots/)
## Quick start
simply do a `docker compose up` in the root of the project and access the frontend at `http://localhost:8080/`. You can also build the image and run the container separately if you want to, or refer the troubleshooting section. 

## Key Features and tools
### Rich data store and accessibility
- Fetch data from multiple sources such as arxiv, PubMed, pdfs, latex, markdown, images, audios, videos, youtube, github, webpages or websites. 
- Add live data sources such as Postgres, MongoDB, CSVs or JSONs, use them for analysis and get insights from them, to aid in the research.
- Separate data collection for each chat to avoid data pollution and ensure relevance of the retrieved data.
- Smart indexing and data retrieval strategies to ensure accuracy at lower costs. 
- Per chat configuration for granular control over model usage.
- Use your data collections or all of your data as MCP context in other tools for more accessibility.

## Key design choices
- **Dynamic config management and support for major providers through a central interface**: Allows user to manage multiple models, tools and data storage setting on a global level, and also on a per chat basis.
- **Fetching top references based on citation counts from data sources for richer context**: Recursively fetches references using the Semantic Scholar API, upto the defined depth; then ranks it based on citation counts and returns the top n results.
- **Runtime retrieval and processing of data**: Ensures that data is fetched and processed in real-time, providing up-to-date information for analysis, for sources such as mongo and postgres. Analysis tool helps with both static data (such as csv and JSONs) or live data (such as databases).
- **Centralized API and frontend**: keeps the application simple
- **Background workers for ingestion and agents**: ensures that the API remains responsive and can handle multiple requests without being blocked by long-running tasks.
- **Orchestrator, Researcher and Checker architecture**: Ensures that high quality, accurate data is fed. Chose this over ReAct because of suitability of this architecture in research scenarios.
- **Websearch on whitelisted sites**: helps with restricted retrieval of data from reliable sources, with support of multiple engines such as Brave (default), Tavily and Serper.
- **Storing all non-analytical data in vector store with rich metadata**: ensures better retrieval and accessibility of data at lower costs, with strategies to optimize data retrieval and keeping LLM usage as little as possible. The rich amount of metadata, paired with 
- **Multiple tools for empowering the agent**: analysis of data, retreival of data from vector store or db, websearch, arxiv/pubmed search.
- **MCP support for reuse of data across chats and tools**: ensures better accessibility of tools and resources.


## Remarks on key decisions
The following decisions were mostly made because LLMs are costly, obviously not immediately on a pet project basis, but on a output to value level, unless they are doing major cost cuttings, I prefer computational methods 
- **Extracting data without LLMs wherever I could**: Such as running OCR on PDF instead of feeding it directly, frame sampling on videos then running OCR on it first and falling back to LLM feedback only as a necessary means, local speech to text, etc.
- **Not using GraphRAG**: Even with an ample amount of data, with smart strategies comparable performance can be obtained without the high costs of running a GraphRAG
- **Running ingestion and agent calls in background worker**: These are CPU intensive tasks and with a lot of request they may overload a server. With a background worker, its easier to maintain reliability

## Future Scopes
Had I had more time with this project, first, I would definetely had made this much more polished :) But apart from that, I would have worked on a good strategy to rank the documents in a study collection. Say, when a researcher is going through a paper, that paper is the primary document, then direct references in it are more important than, say, the youtube videos that the researcher attached to the chat on the same topic. Normalized ranks based on number of citations, relevance score based on topic and the author's profile, (such as an article by a researcher of history might not be as relevant compared to a biochemist's for a user who herself is researching about genetics). That way, because of a more targeted user provided corpus, we can have a great performance at much lower cost when even compared with GraphRAGs.

## API and frontend design
API was mostly vibe coded, and for the frontend i just gave the agent the autogenerated openapi.json along with a few pointers for the interface.

The production container builds the frontend during the image build and serves the compiled app from `/`.
The FastAPI API remains available under `/api`, with MCP routes under `/mcp`.

#### TROUBLESHOOT
In case the docker compose up is not working or taking too long, use the `docker compose -f docker-compose.dependencies.yml up -d` command to start the dependencies (This brings up Redis, Redis Stack, Chroma, and MongoDB without starting the API or the Celery workers).

Then start the API, frontend, and the workers separately, to get started.

```bash
docker compose -f docker-compose.dependencies.yml up -d

# In another terminal
uv run python app/main.py

# In another terminal
celery -A app.workers.ingestion_worker.celery_app worker -Q ingestion --pool=prefork -c 4 -l info --without-gossip --without-mingle

# In another terminal
celery -A app.workers.agent_worker.celery_app worker -Q agent --pool=prefork -c 2 -l info --without-gossip --without-mingle

# And finally, the frontend (this too in another terminal)
cd app/frontend
npm i && npm run dev
```