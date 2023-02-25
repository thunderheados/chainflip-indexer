from python:3.9-alpine
RUN apk add --no-cache gcc musl-dev linux-headers

ADD ./requirements.txt .
RUn pip install -r requirements.txt

ADD . /code
WORKDIR /code

# echo directory
CMD ["python", "/code/main.py"]

