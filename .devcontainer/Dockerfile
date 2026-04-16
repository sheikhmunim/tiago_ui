FROM osrf/ros:noetic-desktop-full

ARG USERNAME=ubuntu
ARG USER_UID=1000
ARG USER_GID=$USER_UID

# Create user if needed
RUN if ! id -u $USER_UID >/dev/null 2>&1; then \
        groupadd --gid $USER_GID $USERNAME && \
        useradd -s /bin/bash --uid $USER_UID --gid $USER_GID -m $USERNAME; \
    fi

# Install base tools and sudo
RUN apt-get update && \
    apt-get install -y sudo git rsync curl ca-certificates gnupg && \
    echo "$USERNAME ALL=(root) NOPASSWD:ALL" > /etc/sudoers.d/$USERNAME && \
    chmod 0440 /etc/sudoers.d/$USERNAME

# Add NodeSource repo and install Node.js 20
RUN mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" > /etc/apt/sources.list.d/nodesource.list && \
    apt-get update && \
    apt-get install -y nodejs && \
    node -v && npm -v

# Install Claude Code
RUN npm install -g @anthropic-ai/claude-code

# Install ROS bridge and video server packages
RUN apt-get update && apt-get install -y \
    ros-noetic-rosbridge-suite \
    ros-noetic-web-video-server \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install Python backend dependencies (system-wide so uvicorn is on PATH)
RUN pip3 install --system fastapi "uvicorn[standard]" 2>/dev/null || \
    pip3 install fastapi "uvicorn[standard]"

# Switch to non-root user
USER $USERNAME

# Add user to video group
RUN sudo usermod --append --groups video $USERNAME

# ROS environment
RUN echo "source /opt/ros/noetic/setup.bash" >> ~/.bashrc

# Rosdep update
RUN rosdep update