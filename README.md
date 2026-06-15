# Coder Workspace Sandbox — Multi-Architecture Reference Manual

This repository contains a dual-tier microservice sandbox (a Vite-powered frontend and a Python FastAPI backend). It serves as an engineering blueprint to evaluate and demonstrate two distinct multi-service architecture patterns inside Coder:

1. **Approach 1**: A single, unified workspace running nested containers via Docker-in-Docker (DinD).
2. **Approach 2**: Multiple, isolated, unprivileged workspace container islands cross-routed via Coder's path-based proxy.

## Architecture 1: Single Workspace via Docker-in-Docker (DinD)
### Strategy Overview
This pattern consolidates both tiers into a single Coder workspace container. It uses a nested hypervisor background daemon (dockerd) to spin up sub-containers on an isolated virtual network bridge. This approach natively leverages your standard devcontainer.json specifications, though it requires enabling kernel-level root privileges (privileged = true).

### Coder Template Configuration
To implement Approach 1, you should replace the template's main.tf with the following code configuration:
```terraform
terraform {
  required_providers {
    coder = {
      source = "coder/coder"
    }
    docker = {
      source = "kreuzwerker/docker"
    }
  }
}

locals {
  username = data.coder_workspace_owner.me.name
}

variable "docker_socket" {
  default     = ""
  description = "(Optional) Docker socket URI"
  type        = string
}

provider "docker" {
  # Defaulting to null if the variable is an empty string lets us have an optional variable without having to set our own default
  host = var.docker_socket != "" ? var.docker_socket : null
}

data "coder_provisioner" "me" {}
data "coder_workspace" "me" {}
data "coder_workspace_owner" "me" {}

resource "coder_agent" "main" {
  arch           = data.coder_provisioner.me.arch
  os             = "linux"
  startup_script = <<-EOT
    set -e

    # Prepare user home with default files on first start.
    if [ ! -f ~/.init_done ]; then
      cp -rT /etc/skel ~
      touch ~/.init_done
    fi

    # Add any commands that should be executed at workspace startup (e.g install requirements, start a program, etc) here
    echo "--- 📦 Bootstrapping Environment for Docker Compose ---"
    sudo apt-get update

    # 1. Install Node.js & npm (Kept for environment stability)
    echo "--- 🟢 Installing Node and NPM ---"
    sudo apt-get install -y nodejs npm

    # 2. Install Docker Natively
    echo "--- 🐳 Installing Docker Engine ---"
    if ! command -v docker &> /dev/null; then
      sudo apt-get install -y docker.io
      sudo usermod -aG docker coder
    fi

    # 3. Natively start and wait for the Docker background engine using VFS fallback driver
    echo "--- 🔌 Starting Docker Daemon Service ---"
    if ! pgrep dockerd > /dev/null; then
      # Passing the VFS driver bypasses the layer conversion errors inside user namespaces!
      sudo dockerd --storage-driver vfs > /tmp/dockerd.log 2>&1 &
    fi
    
    # Wait up to 10 seconds for the docker socket to become active
    for i in {1..10}; do
      if sudo docker info &> /dev/null; then
        echo "--- ✅ Docker engine is live and responding! ---"
        break
      fi
      echo "Waiting for Docker service to start..."
      sleep 1
    done

    # 4. Pull your project sandbox files
    if [ ! -d "backend" ]; then
      echo "--- 📥 Cloning Sandbox Repository ---"
      git clone https://github.com/mandanakhademi/coder-multi-workspace-sandbox.git temp-repo
      cp -r temp-repo/. .
      rm -rf temp-repo
    fi

    # === FORCE THE CORRECT PROXY FILE BEFORE COMPOSE LAUNCHES ===
    echo "--- 🛠️ Injecting persistent proxy configuration into frontend ---"
    cat << 'EOF' > ~/frontend/vite.config.js
import { defineConfig } from 'vite'

export default defineConfig({
  server: {
    host: '0.0.0.0',
    port: 3000,
    allowedHosts: true,
    proxy: {
      '/api': {
        target: 'http://backend:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '')
      }
    }
  }
})
EOF

    # =====================================================

    # 5. Execute your architectural configuration directly via Compose!
    echo "--- 🚀 Launching Multi-Container Environment via Compose ---"
    cd .devcontainer
    docker compose down --remove-orphans || true # Ensure we clear any stuck layers
    docker compose up -d --remove-orphans
  EOT

  # These environment variables allow you to make Git commits right away after creating a
  # workspace. Note that they take precedence over configuration defined in ~/.gitconfig!
  # You can remove this block if you'd prefer to configure Git manually or using
  # dotfiles. (see docs/dotfiles.md)
  env = {
    GIT_AUTHOR_NAME     = coalesce(data.coder_workspace_owner.me.full_name, data.coder_workspace_owner.me.name)
    GIT_AUTHOR_EMAIL    = "${data.coder_workspace_owner.me.email}"
    GIT_COMMITTER_NAME  = coalesce(data.coder_workspace_owner.me.full_name, data.coder_workspace_owner.me.name)
    GIT_COMMITTER_EMAIL = "${data.coder_workspace_owner.me.email}"
  }

  # The following metadata blocks are optional. They are used to display
  # information about your workspace in the dashboard. You can remove them
  # if you don't want to display any information.
  # For basic resources, you can use the `coder stat` command.
  # If you need more control, you can write your own script.
  metadata {
    display_name = "CPU Usage"
    key          = "0_cpu_usage"
    script       = "coder stat cpu"
    interval     = 10
    timeout      = 1
  }

  metadata {
    display_name = "RAM Usage"
    key          = "1_ram_usage"
    script       = "coder stat mem"
    interval     = 10
    timeout      = 1
  }

  metadata {
    display_name = "Home Disk"
    key          = "3_home_disk"
    script       = "coder stat disk --path $${HOME}"
    interval     = 60
    timeout      = 1
  }

  metadata {
    display_name = "CPU Usage (Host)"
    key          = "4_cpu_usage_host"
    script       = "coder stat cpu --host"
    interval     = 10
    timeout      = 1
  }

  metadata {
    display_name = "Memory Usage (Host)"
    key          = "5_mem_usage_host"
    script       = "coder stat mem --host"
    interval     = 10
    timeout      = 1
  }

  metadata {
    display_name = "Load Average (Host)"
    key          = "6_load_host"
    # get load avg scaled by number of cores
    script   = <<EOT
      echo "`cat /proc/loadavg | awk '{ print $1 }'` `nproc`" | awk '{ printf "%0.2f", $1/$2 }'
    EOT
    interval = 60
    timeout  = 1
  }

  metadata {
    display_name = "Swap Usage (Host)"
    key          = "7_swap_host"
    script       = <<EOT
      free -b | awk '/^Swap/ { printf("%.1f/%.1f", $3/1024.0/1024.0/1024.0, $2/1024.0/1024.0/1024.0) }'
    EOT
    interval     = 10
    timeout      = 1
  }
}

# See https://registry.coder.com/modules/coder/code-server
module "code-server" {
  count  = data.coder_workspace.me.start_count
  source = "registry.coder.com/coder/code-server/coder"

  # This ensures that the latest non-breaking version of the module gets downloaded, you can also pin the module version to prevent breaking changes in production.
  version = "~> 1.0"

  agent_id = coder_agent.main.id
  order    = 1
}

# See https://registry.coder.com/modules/coder/jetbrains
module "jetbrains" {
  count      = data.coder_workspace.me.start_count
  source     = "registry.coder.com/coder/jetbrains/coder"
  version    = "~> 1.1"
  agent_id   = coder_agent.main.id
  agent_name = "main"
  folder     = "/home/coder"
  tooltip    = "You need to [install JetBrains Toolbox](https://coder.com/docs/user-guides/workspace-access/jetbrains/toolbox) to use this app."
}

resource "docker_volume" "home_volume" {
  name = "coder-${data.coder_workspace.me.id}-home"
  # Protect the volume from being deleted due to changes in attributes.
  lifecycle {
    ignore_changes = all
  }
  # Add labels in Docker to keep track of orphan resources.
  labels {
    label = "coder.owner"
    value = data.coder_workspace_owner.me.name
  }
  labels {
    label = "coder.owner_id"
    value = data.coder_workspace_owner.me.id
  }
  labels {
    label = "coder.workspace_id"
    value = data.coder_workspace.me.id
  }
  # This field becomes outdated if the workspace is renamed but can
  # be useful for debugging or cleaning out dangling volumes.
  labels {
    label = "coder.workspace_name_at_creation"
    value = data.coder_workspace.me.name
  }
}

resource "docker_container" "workspace" {
  count = data.coder_workspace.me.start_count
  image = "codercom/enterprise-base:ubuntu"
  # Uses lower() to avoid Docker restriction on container names.
  name  = "coder-${data.coder_workspace_owner.me.name}-${lower(data.coder_workspace.me.name)}"
  
  # === ADD THIS ONE LINE TO YOUR ORIGINAL BLOCK ===
  privileged = true
  # ===============================================

  # Hostname makes the shell more user friendly: coder@my-workspace:~$
  hostname = data.coder_workspace.me.name
  # Use the docker gateway if the access URL is 127.0.0.1
  entrypoint = ["sh", "-c", replace(coder_agent.main.init_script, "/localhost|127\\.0\\.0\\.1/", "host.docker.internal")]
  env = ["CODER_AGENT_TOKEN=${coder_agent.main.token}"]
  host {
    host = "host.docker.internal"
    ip = "host-gateway"
  }
  volumes {
    container_path = "/home/coder"
    volume_name = docker_volume.home_volume.name
    read_only = false
  }

  # Add labels in Docker to keep track of orphan resources.
  labels {
    label = "coder.owner"
    value = data.coder_workspace_owner.me.name
  }
  labels {
    label = "coder.owner_id"
    value = data.coder_workspace_owner.me.id
  }
  labels {
    label = "coder.workspace_id"
    value = data.coder_workspace.me.id
  }
  labels {
    label = "coder.workspace_name"
    value = data.coder_workspace.me.name
  }
}
```

### Presentation Layer Manual Interface Replacement (index.html)
You need to open a terminal on the workspace and run the following commands to replace the index.html file.
```bash
cd frontend
cat << 'EOF' > index.html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GDS Coder Frontend</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; padding: 40px; background: #f4f6f8; color: #333; }
        .card { background: white; padding: 24px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); max-width: 600px; margin-bottom: 20px; }
        .status-badge { background: #d4edda; color: #155724; padding: 6px 12px; border-radius: 20px; font-weight: bold; font-size: 0.9em; display: inline-block; }
        button { background: #005a36; color: white; border: none; padding: 10px 20px; border-radius: 4px; cursor: pointer; font-size: 1em; }
        button:hover { background: #004428; }
    </style>
</head>
<body>

    <div class="card">
        <h1>🌐 Coder UI Sandbox Workspace</h1>
        <p>This frontend application is running on port <strong>3000</strong>.</p>
        <button id="fetchBtn">Fetch Data from Backend</button>
    </div>

    <div class="card" id="apiResponseCard" style="display: none;">
        <h3>📡 Backend Connection Status:</h3>
        <p id="backendStatus"><span class="status-badge">Connecting...</span></p>
        <h3>📋 Data Retrieved:</h3>
        <ul id="dataList"></ul>
    </div>

    <script type="module">
        // Points natively to the internal container channel path
        const PROXY_URL = '/api';

        document.getElementById('fetchBtn').addEventListener('click', async () => {
            const responseCard = document.getElementById('apiResponseCard');
            const statusEl = document.getElementById('backendStatus');
            const listEl = document.getElementById('dataList');

            responseCard.style.display = 'block';
            listEl.innerHTML = '';

            try {
                // 1. Fetch from root endpoint
                const rootRes = await fetch(`${PROXY_URL}/`);
                const rootData = await rootRes.json();
                statusEl.innerHTML = `<span class="status-badge">${rootData.message}</span>`;

                // 2. Fetch from data endpoint
                const dataRes = await fetch(`${PROXY_URL}/api/data`);
                const data = await dataRes.json();

                data.items.forEach(item => {
                    const li = document.createElement('li');
                    li.innerHTML = `<strong>${item.name}</strong> - ${item.complete ? '✅ Done' : '⏳ In Progress'}`;
                    listEl.appendChild(li);
                });
            } catch (error) {
                statusEl.innerHTML = `<span style="color: red; font-weight: bold;">❌ Cannot connect to backend proxy context</span>`;
                console.error("Connection error:", error);
            }
        });
    </script>
</body>
</html>
EOF
```
