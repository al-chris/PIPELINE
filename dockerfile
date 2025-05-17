# syntax=docker/dockerfile:1
FROM python:3.13-alpine

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# Install system dependencies (ALPINE VERSION)
RUN apk update && apk add --no-cache \
    build-base \
    libpq \
    gcc \
    postgresql-dev

# Install pip and poetry
RUN pip install --upgrade pip

# Copy project files
COPY . /app/

# Install dependencies
RUN pip install --no-cache-dir .

# Expose port for FastAPI
EXPOSE 8000

# Start the FastAPI app with uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]