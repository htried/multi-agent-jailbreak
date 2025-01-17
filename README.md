# Secure Agent Project

A secure Docker-based environment for running automated browser tasks with Playwright.

## Prerequisites

- Docker
- Docker Compose
- Git

## Project Structure

```
multi-agent-jailbreak/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env
├── .gitignore
├── README.md
└── app/
    ├── init.py
    ├── main.py
    ├── config.py
    ├── rate_limiter.py
    ├── security.py
    ├── browser.py
    ├── logs/
    └── tests/
```

## Setup

1. Clone the repository:

```bash
git clone https://github.com/htried/multi-agent-jailbreak.git
cd multi-agent-jailbreak
```

2. Create a `.env` file with the following variables:

```
GOOGLE_API_KEY=your_google_api_key
MAX_REQUESTS_PER_MINUTE=30
ALLOWED_DOMAINS=domain1.com,domain2.com
DEBUG=False
```

3. Build the Docker container:

```bash
docker compose build
```

## Running the application

### Start the container:
```bash
# Run in the foreground
docker compose up

# Run in the background
docker compose up -d
```

### View logs:

```bash
docker compose logs -f
```

### View recent logs:

```bash
docker compose logs --tail 100
```

### Stop the container:

```bash
docker compose down
```

## Development

### Accessing the container:

```bash
docker-compose exec agent bash
```

### Running tests:

```bash
# Run all tests in the container

docker-compose run --rm agent python -m pytest app

# Run a specific test file

docker-compose run --rm agent python -m pytest app/tests/test_example.py
```

## Logging

Logs are stored in `app/logs/` with rotation enabled:
- Maximum file size: 10MB
- Backup count: 5 files

## Troubleshooting

### Common Issues

1. **Container fails to start**
   - Check Docker logs: `docker-compose logs`
   - Verify system resources
   - Ensure all required environment variables are set

2. **Playwright browser launch fails**
   - Verify system dependencies: `docker-compose exec agent playwright install --with-deps chromium`
   - Check shared memory size
   - Ensure container has necessary permissions

3. **Memory issues**
   - Increase Docker memory limit in `docker-compose.yml`
   - Check for memory leaks in browser automation
   - Monitor container resources: `docker stats`

## Security scanning

```bash
# run a security check on the container
docker-compose exec agent pip-audit
```

## License

tktk

## Contact

For questions or support, please contact:

- [Hal Triedman](mailto:triedman@cs.cornell.edu)
