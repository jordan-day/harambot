# Use an official Python runtime as a parent image
FROM python:3.9

# Set the working directory to /app
WORKDIR /app

# Copy the local package to the container's /app directory
COPY . /app

# Install your Python package and its dependencies
RUN pip install .

# Define the command to run your package (adjust as needed)
CMD ["python", "harambot/bot.py"]
