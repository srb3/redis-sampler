# Use a base image with Python
FROM python:3.9-slim

# Set environment variables to prevent Python from writing .pyc files and buffering stdout and stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Create and set the working directory
WORKDIR /app

# Copy the requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the script into the container
COPY redis_sample_prometheus.py .

# Expose the port for Prometheus to scrape metrics
EXPOSE 8881

# Set the entrypoint to run the script with default arguments
ENTRYPOINT ["python", "redis_sample_prometheus.py"]
