# Use the official Python 3.9 slim image as a parent image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /code

# Copy the requirements file into the container at /code
COPY ./requirements.txt /code/requirements.txt

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# Copy the app directory into the container at /code
COPY ./app /code/app

# Expose port 8006 to the outside world
EXPOSE 8006

# Command to run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8006"]
