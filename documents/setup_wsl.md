# Setup for WSL (Ubuntu):
This file contains the set up instruction for running the app on WSL `(Ubuntu 22.04 or 24.04)`

## Install Docker Windows
Install Docker Destop in Windows computer

## Install Ubuntu from Microsoft Store (one of the two versions)
 - Ubuntu 24.04
 - Ubuntu 22.04

## System Dependencies
### Update system packages
```bash
sudo apt update -y
sudo apt upgrade -y
```

### Install essential system packages:
```bash
# Install system utilities and development tools
sudo apt-get install -y \
    curl wget git-lfs cmake \
    portaudio19-dev python3-all-dev \
    python3 python3-pip git-all tmux \
    libomp-dev tesseract-ocr libtesseract-dev

# Install snapd package manager
sudo apt install snapd

# Install multimedia tools
sudo snap install --edge ffmpeg
```

### Install Node.js (v20.x):
```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash - 
sudo apt-get install -y nodejs
```

### Install Miniconda for Python environment management
```bash
mkdir -p ~/miniconda3
ARCH=$(uname -m)
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-${ARCH}.sh -O ~/miniconda3/miniconda.sh
bash ~/miniconda3/miniconda.sh -b -u -p ~/miniconda3
rm ~/miniconda3/miniconda.sh
~/miniconda3/bin/conda init bash
source ~/.bashrc
```

### Setup internet connection for Docker
#### Ubuntu 24.04
- Open Docker Desktop application
- Go to Settings -> Docker Engine
- Add this as an extra field in the Docker daemon json
    ```bash
    "dns": ["10.1.2.3", "8.8.8.8"]
    ```

#### Ubuntu 22.04
- Run this command
    ```bash
    cd /etc/docker
    ```
- Adjust the daemon.json file content
    ```bash
    sudo nano /etc/docker/daemon.json
    ```
- Add this and save the daemon file
    ```bash
    "dns": ["10.1.2.3", "8.8.8.8"]
    ```

### Change IP Table to legacy (both IPv4 and IPv6)
- Check if `iptables` is available on your WSL
    ```bash
    iptables -V
    ```
- If not, install `iptables`
    ```bash
    sudo apt install iptables
    ```
- Switch to legacy mode for IPv4 and IPv6
    ```bash
    sudo update-alternatives --set iptables /usr/sbin/iptables-legacy
    sudo update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy
    ```
- Verify the change (ensure legacy)
    ```bash
    sudo iptables --version
    sudo ip6tables --version
    ```

### Set up NVIDIA GPU support inside Docker
- Install NVIDIA Container Toolkit
    ```bash
    sudo apt install -y nvidia-container-toolkit
    ```
- Run a test CUDA container
    ```bash
    docker run --rm --gpus all nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi
    ```

### Configure Docker permissions
```bash
sudo usermod -aG docker $USER
newgrp docker
exec su -l $USER
```

### Install Rust toolchain
```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source $HOME/.cargo/env
```

### Common Dependencies
#### Install Node Version Manager (nvm)
```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
```

#### Set up Python environment
```bash
conda create --name dev python=3.11
```

## Project Setup
### Install Python dependencies
```bash
# Activate development environment
conda deactivate && conda activate dev

# Install development dependencies
pip install -r apps/requirements/dev.langchain.requirements.txt 

# Install core service dependencies
pip install -r apps/services/core.requirements.txt
```

### Service Configuration
Configure audio services
```bash
# Configure Piper
chmod +x ./apps/services/audio/text_to_speech/impl/assets/setup.piper.sh
./apps/services/audio/text_to_speech/impl/assets/setup.piper.sh

# Configure Whisper
chmod +x ./apps/services/audio/speech_to_text/impl/assets/setup.whisper_cpp.sh
./apps/services/audio/speech_to_text/impl/assets/setup.whisper_cpp.sh
```

#### Data Initialization
- Run the setup notebook at `apps/services/projects/vehicle/setup.ipynb`
- OR: Run the setup script at `apps/services/projects/vehicle/setup.py`

### Infrastructure Setup
Ensure you are at the repository directory for each command
```bash
cd apps/toolkit/utils/scripts/
conda deactivate && conda activate dev
python envs.py vehicle "../../../../front_end/Nuxt/.env"
```

#### Frontend setup
```bash
cp apps/context/app/infra.json front_end/Nuxt/configs/
cp apps/context/app/ml.json front_end/Nuxt/configs/
cp apps/context/app/vehicle.json front_end/Nuxt/configs/
```
```bash
cd front_end/Nuxt
npm install
npm run build
```

#### Ensure face detection model exists
```bash
if [ ! -d "apps/services/image/detection/faces/impl/libfacedetection" ]; then
  git clone https://github.com/ShiqiYu/libfacedetection.git apps/services/image/detection/faces/impl/libfacedetection
else
  cd apps/services/image/detection/faces/impl/libfacedetection && git pull origin master
fi
```


```bash
if [ ! -f "apps/services/image/detection/faces/impl/libfacedetection/opencv_dnn/python/face_detection_yunet_2023mar_int8bq.onnx" ]; then
  echo "Model file not found. Downloading..."
  wget -L "https://github.com/opencv/opencv_zoo/raw/refs/heads/main/models/face_detection_yunet/face_detection_yunet_2023mar_int8bq.onnx?download=" -O "apps/services/image/detection/faces/impl/libfacedetection/opencv_dnn/python/face_detection_yunet_2023mar_int8bq.onnx"
else
  echo "Model file already exists. Skipping download."
fi
```

#### Launch required Docker containers
- For first time setup
    ```bash
    docker compose -f devops/docker/infra/docker-compose.yaml up -d
    docker compose -f devops/docker/apps/vehicle/services.docker-compose.yaml up --build -d
    docker compose -f devops/docker/apps/vehicle/main.docker-compose.yaml up --build -d
    ```
- For later runs (omit the `--build` unless the images has changed)
     ```bash
    docker compose -f devops/docker/infra/docker-compose.yaml up -d
    docker compose -f devops/docker/apps/vehicle/services.docker-compose.yaml up -d
    docker compose -f devops/docker/apps/vehicle/main.docker-compose.yaml up -d
    ```
- The application will run at `http://localhost:3000/ui/ai/vehicle`

## Validation
### Service Testing
```bash
cd apps/services/SERVICE
conda deactivate && conda activate dev
python server.py
```

Access each service's UI at `http://localhost:PORT/ui` (PORT will be displayed in terminal)

### Application Testing

Test the LLM agent functionality using the development notebook:
`apps/services/llm/agents/vehicle/dev.ipynb`

## Troubleshooting
Common issues and solutions:
1. If Docker fails to start:
   - Ensure Docker daemon is running: `sudo systemctl status docker`
   - Check if user is in docker group: `groups $USER`

2. If Python packages fail to install:
   - Verify conda environment is active: `conda info --envs`
   - Update pip: `pip install --upgrade pip`

3. If services fail to start:
   - Check port availability: `netstat -tulpn`
   - Verify all Docker containers are running: `docker ps`
   - Check service logs: `docker logs <container_name>`

For additional support, consult the project documentation or open an issue in the repository.