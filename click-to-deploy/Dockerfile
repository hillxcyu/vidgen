# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

FROM python:3.11-slim

# Install system dependencies (ffmpeg, opencv requirements)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Supply-chain compliant dependency installation (pinned versions + SHA256 hashes)
COPY click-to-deploy/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --require-hashes -r requirements.txt

# Copy application source
COPY app/ ./app/
COPY src/ ./src/
COPY Skill/ ./Skill/

ENV PORT=8080
ENV GOOGLE_CLOUD_LOCATION=global
ENV GOOGLE_GENAI_USE_VERTEXAI=true

CMD ["sh", "-c", "uvicorn app.fast_api_app:app --host 0.0.0.0 --port ${PORT}"]
