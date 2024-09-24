import subprocess
import os
import sys
import time
import psutil
import libs.config_parser as config_parser
from data.constants import *
import re
import yaml

def run_subprocess(command, dest_dir=None, timeout=None):
    if dest_dir:
        os.chdir(dest_dir)

    print("Starting Process %s from %s" %(command, os.getcwd()))
    process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    universal_newlines=True, shell=True, timeout=timeout)
    try:
        if dest_dir: os.chdir(FRAMEWORK_PATH)
    except:
        print("Failed to change directory")

    if process.returncode != 0:
        print(process.stderr.strip())
        raise Exception("Failed to run command {}".format(command))
    
    return process.stdout.strip()

def execute_cmd(command, dest_dir=None, timeout=None):
    try:
        if dest_dir:
            os.chdir(dest_dir)

        print("Starting Process %s from %s" %(command, os.getcwd()))
        process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    universal_newlines=True, shell=True, timeout=timeout)
        if dest_dir: os.chdir(FRAMEWORK_PATH)
    except subprocess.TimeoutExpired:
        pass


def popen_subprocess(command, dest_dir=None):
    if dest_dir:
        os.chdir(dest_dir)

    print("Starting Process ", command)
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, encoding='utf-8')
    time.sleep(1)
   
    if dest_dir: os.chdir(FRAMEWORK_PATH)
    return process

def kill(proc_pid):
    try:
        process = psutil.Process(proc_pid)
        for proc in process.children(recursive=True):
            proc.terminate()
        process.terminate()
    except:
        pass

def kill_process_by_name(processName):
    procs = [p for p in psutil.process_iter() for c in p.cmdline() if processName in c]
    for process in procs:
        try:
            run_subprocess("kill -9 {}".format(process.pid))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

def is_package_installed(package_name):
    process = subprocess.run(f"apt list --installed | grep {package_name}", stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, universal_newlines=True,
                                shell=True)


    if process.returncode != 0:
        print(f"Package: {package_name} is not installed")
        return False
    print(f"Package: {package_name} installation found. Details {process.stdout.strip()}")

    return True

def stop_docker_process(keyword):
    container_id = run_subprocess(f"docker container ls  | grep {keyword}" +" | awk '{print $1}'")
    if container_id:
        try:
            run_subprocess("docker stop {}".format(container_id))
        except Exception as e:
            pass

def cleanup_after_test(test_config_dict):
    try:
        docker_image = test_config_dict['docker_image'].split(" ")[1]
        copy_cmd = "mv {} {}.txt >/dev/null 2>&1".format(test_config_dict["curation_log"], 
                                    os.path.join(LOGS, test_config_dict["test_name"]))
        run_subprocess(copy_cmd)
        if test_config_dict["attestation"]:
            verifier_cmd = "mv {} {} >/dev/null 2>&1".format(os.path.join(CURATED_APPS_PATH,"verifier/verifier.log"),
            os.path.join(LOGS, f'{test_config_dict["test_name"]}_verifier.log'))
            run_subprocess(verifier_cmd)
        stop_docker_process("verifier:latest")
        stop_docker_process("gramine")
        run_subprocess("docker rmi verifier:latest -f")
        run_subprocess(f"docker rmi gsc-{docker_image} -f")
        run_subprocess("docker stop init_test_db &>/dev/null")
        if test_config_dict.get("create_local_image") == "y":
            run_subprocess(f"docker rmi {docker_image} -f >/dev/null 2>&1")
        if run_subprocess("docker ps -a -f status=exited -f status=created -q"):
            run_subprocess("docker rm $(docker ps -a -f status=exited -f status=created -q)")
    except Exception as e:
        print("Exception occured during cleanup ", e)

def get_workload_name(docker_image):
    try:
        return docker_image.split(" ")[0]
    except Exception as e:
        return ''

def check_machine():
    service_cmd = "sudo systemctl --type=service --state=running"
    service_output = run_subprocess(service_cmd)
    if "walinuxagent.service" in service_output or "waagent.service" in service_output:
        # 'loaded active running Azure Linux Agent'
        print("Running on Azure Linux Agent")
        return "Azure Linux Agent"
    elif "pccs.service" in service_output:
        # 'loaded active running Provisioning Certificate Caching Service (PCCS)'
        print("Running on DCAP client")
        return "DCAP client"
    else:
        print("No Provisioning service found, cannot run tests with attestation.")
        return "No Provisioning enabled"

def create_docker_image(docker_path, docker_name):
    docker_build_cmd = "docker build -t %s ." % docker_name
    print("docker build cmd is ", docker_build_cmd)
    output = run_subprocess(docker_build_cmd, docker_path)
    print(output)

def generate_local_image(test_config_dict):
    workload_name, image_name = test_config_dict["docker_image"].split(" ", 1)

    if "pytorch" in workload_name:
        if "latest" in test_config_dict["test_name"]:
            run_subprocess(PYTORCH_UPDATE_APP_VERSION, PYTORCH_HELPER_PATH)
        output = run_subprocess(PYTORCH_HELPER_CMD, CURATED_APPS_PATH)
        print(output)
    elif "bash" in workload_name:
        create_docker_image(BASH_PATH, image_name)
    elif "sklearn" in workload_name:
        if "latest" in test_config_dict["test_name"]:
            run_subprocess(SKLEARN_UPDATE_APP_VERSION, SKLEARN_HELPER_PATH)
        output = run_subprocess(SKLEARN_HELPER_CMD, CURATED_APPS_PATH)
        print(output)
    elif "tensorflow-serving" in workload_name:
        output = run_subprocess(TFSERVING_HELPER_CMD, CURATED_APPS_PATH)
        print(output)

def init_db(workload_name, init_cmd):
    docker_output = ''
    output=None
    init_result = False
    timeout = time.time() + 60*2
    try:
        create_test_db = "mkdir -p " + eval(workload_name.upper() + "_TESTDB_PATH")
        mkdir_output = run_subprocess(create_test_db, CURATED_APPS_PATH)
        print(mkdir_output)
        process = subprocess.Popen(init_cmd, cwd=CURATED_APPS_PATH, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        print(f"Initializing {workload_name.upper()} DB")
        while True:
            if process.poll() is not None and output == '':
                if "ovms" in workload_name:
                    time.sleep(30)
                    if os.path.exists(os.path.join(CURATED_APPS_PATH, OVMS_TESTDB_PATH, \
                        "1/face-detection-retail-0004.bin")) and \
                        os.path.exists(os.path.join(CURATED_APPS_PATH, OVMS_TESTDB_PATH, \
                        "1/face-detection-retail-0004.xml")):
                        print(f"{workload_name.upper()} DB is initialized\n")
                        init_result = True
                        break
                else:
                    break
            output = process.stderr.readline()
            print(output)
            if output:
                docker_output += output
                if "mysql" in workload_name or "mariadb" in workload_name:
                    if (docker_output.count(eval(workload_name.upper()+"_TESTDB_VERIFY")) == 2):
                        print(f"{workload_name.upper()} DB is initialized\n")
                        init_result = True
                        break
                    elif time.time() > timeout:
                        break
    finally:
        process.stdout.close()
        process.stderr.close()
        kill(process.pid)
    if init_result:
        if "mysql" in workload_name or "mariadb" in workload_name:
            run_subprocess(STOP_TEST_DB_CMD, CURATED_APPS_PATH)
        if "mariadb" in workload_name:
            run_subprocess(MARIADB_CHMOD, CURATED_APPS_PATH)
    return init_result

def encrypt_db(workload_name):
    if (workload_name in ["mariadb", "ovms"]):
        run_subprocess(DB_MOUNT + eval(workload_name.upper()+"_ENC_PATH"), CURATED_APPS_PATH)
    if (workload_name == "ovms"):
        enc_key_path = "workloads/" + OVMS + "/base_image_helper/encryption_key"
    else:
        enc_key_path = "workloads/" + workload_name + "/base_image_helper/encryption_key"
    enc_key = "dd if=/dev/urandom bs=16 count=1 > " + enc_key_path
    encrypt_db_cmd = "gramine-sgx-pf-crypt encrypt -w " + enc_key_path + " -i " + \
                        eval(workload_name.upper()+"_TESTDB_PATH") + " -o " + \
                        eval(workload_name.upper()+"_ENC_PATH")
    cleanup_db = "rm -rf " + eval(workload_name.upper()+"_ENC_PATH") + "/*"

    if workload_name == "mysql":
        encrypt_db_cmd = "sudo " + encrypt_db_cmd
        cleanup_db = "sudo " + cleanup_db

    run_subprocess(enc_key, CURATED_APPS_PATH)
    run_subprocess(cleanup_db, CURATED_APPS_PATH)
    run_subprocess(encrypt_db_cmd, CURATED_APPS_PATH)

def execute_pre_workload_setup(test_config_dict):
    workload_name = get_workload_name(test_config_dict["docker_image"])
    docker_image = test_config_dict["docker_image"].split(" ")[1]
    if workload_name in ["mysql", "mariadb", "openvino-model-server"]:
        if workload_name == "openvino-model-server":
            workload_name = "ovms"
            port_pid_cmd = "$(sudo lsof -t -i:8500)"
            port_pid_cmd = run_subprocess(f"{port_pid_cmd}")
            print("***********************{}".format(port_pid_cmd))
            if port_pid_cmd:
                print("Killing {}".format(port_pid_cmd))
                run_subprocess(f"kill -9 {port_pid_cmd}")
        init_cmd = eval(workload_name.upper()+"_INIT_DB_CMD")
        if workload_name == "mysql" and docker_image not in init_cmd:
            print("*********************** inside if")
            port_pid_cmd = "$(sudo lsof -t -i:33060)"
            port_pid_cmd = run_subprocess(f"{port_pid_cmd}")
            print("***********************{}".format(port_pid_cmd))
            if port_pid_cmd:
                print("Killing {}".format(port_pid_cmd))
                run_subprocess(f"kill -9 {port_pid_cmd}")
            init_cmd = init_cmd.replace(MYSQL_CURR_VERSION, docker_image)
        elif workload_name == "mariadb" and docker_image not in init_cmd:
            port_pid_cmd = "$(sudo lsof -t -i:33060)"
            port_pid_cmd = run_subprocess(f"{port_pid_cmd}")
            print("***********************{}".format(port_pid_cmd))
            if port_pid_cmd:
                print("Killing {}".format(port_pid_cmd))
                run_subprocess(f"kill -9 {port_pid_cmd}")
            init_cmd = init_cmd.replace(MARIADB_CURR_VERSION, docker_image)
        init_result = init_db(workload_name, init_cmd)
        if workload_name == "mysql":
            print("*********************** inside if")
            port_pid_cmd = "$(sudo lsof -t -i:33060)"
            port_pid_cmd = run_subprocess(f"{port_pid_cmd}")
            print("***********************{}".format(port_pid_cmd))
            if port_pid_cmd:
                print("Killing {}".format(port_pid_cmd))
                run_subprocess(f"kill -9 {port_pid_cmd}")
        if init_result == False:
            sys.exit("DB initialization failed")
        encrypt_db(workload_name)

def local_image_setup(test_config_dict):
    if test_config_dict.get("create_local_image") == "y":
        generate_local_image(test_config_dict)

def test_setup(test_config_dict):
    if test_config_dict.get("test_option") == None:
        sorted_dict = config_parser.data_pre_processing(test_config_dict)
        input_str = config_parser.convert_dict_to_str(sorted_dict)
        config_parser.create_input_file(input_str)
    else:
        config_parser.create_input_file(b'\x07')
    if test_config_dict.get("encrypted_files_path"):
        check_and_install_gramine()
    if test_config_dict.get("pre_workload_setup") == "y":
        pre_workload_setup_result = execute_pre_workload_setup(test_config_dict) 
    local_image_setup(test_config_dict)
    time.sleep(5)

def read_file(filename):
    fd = open(filename)
    fd_contents = fd.read()
    fd.close()
    return fd_contents

def update_file_contents(old_contents, new_contents, filename, append=False):
    fd_contents = read_file(filename)
    if append:
        old_data = (old_contents).join(re.search("(.*){}(.*)".format(old_contents), fd_contents).groups())
        new_data = re.sub(old_data, new_contents+old_data, fd_contents)
    else:
        new_data = re.sub(old_contents, new_contents, fd_contents)
    fd = open(filename, "w")
    fd.write(new_data)
    fd.close()

def check_and_install_gramine():
    gramine_path = None
    try:
        gramine_path = run_subprocess("which gramine-sgx")
    except Exception as e:
        pass
    if not gramine_path:
        run_subprocess("sudo curl -fsSLo /usr/share/keyrings/gramine-keyring.gpg https://packages.gramineproject.io/gramine-keyring.gpg")
        run_subprocess('echo "deb [arch=amd64 signed-by=/usr/share/keyrings/gramine-keyring.gpg] https://packages.gramineproject.io/ $(lsb_release -sc) main" | sudo tee /etc/apt/sources.list.d/gramine.list')
        run_subprocess("sudo apt-get update")
        run_subprocess(f"{APT_INSTALL} {GRAMINE}")
    else:
        print("Gramine Installation Found at: ", gramine_path)

def check_app_version(test_config_dict):
    app_image = test_config_dict['docker_image'].split(" ")[1]
    app_name = test_config_dict['docker_image'].split(" ")[0]
    if app_name == "openvino-model-server":
        version_string = run_subprocess(f"docker run {app_image} --version | grep 'OpenVINO Model Server'")
        version = version_string.split("OpenVINO Model Server ")[1]
    elif app_name == "sklearn":
        app_image = "intel/intel-optimized-ml:latest"
        run_subprocess(f"docker pull {app_image}")
        version_string = run_subprocess(f"docker inspect {app_image} | grep intel/intel-optimized-ml@sha256:")
        version = version_string.split(":")[1].strip('"')
    elif app_name == "mariadb":
        version_string = run_subprocess(f"docker inspect {app_image} | grep -m 1 {app_name.upper()}_VERSION")
        version = version_string.split(":")[1].split("+")[0]
    elif app_name == "mysql" or app_name == "redis":
        version_string = run_subprocess(f"docker inspect {app_image} | grep -m 1 {app_name.upper()}_VERSION")
        version = version_string.split("=")[1].strip(",").strip('"')
    elif app_name == "pytorch":
        version_string = run_subprocess(f"docker inspect {app_image} | grep {app_name.upper()}_VERSION")
        version = version_string.split("\n")[0].split("=")[1].strip('"')
    elif app_name == "memcached":
        version_string = run_subprocess(f"docker run {app_image} --version | grep memcached")
        version = version_string.split("memcached ")[1]
    print(f"App name {app_name} Version is {version}")
    if version == BASELINE_APP_VERSION[app_name]:
        print("App version is still the same as baseline version")
        return True
    else:
        print("App version has upgraded to a newer version")
        return False

def verify_build_env_details():
    result = False
    out = []
    if os.environ["gramine_commit"] or os.environ["gsc_repo"] or os.environ["gsc_commit"]:
        print("\n\n############################################################################")
        os.chdir(os.path.join(CURATED_APPS_PATH, "gsc"))
        if os.environ["gramine_commit"]:
            fd = open("config.yaml", mode="r")
            fd_data = yaml.safe_load(fd.read())
            c_gramine_repo = fd_data["Gramine"]["Repository"]
            c_gramine_commit = fd_data["Gramine"]["Branch"]
            out.append(os.environ["gramine_commit"] == c_gramine_commit)
            print("\nGramine Repo: ", c_gramine_repo)
            print("Gramine Commit: ", c_gramine_commit)
        if os.environ["gsc_repo"]:
            c_gsc_url = run_subprocess("git config --get remote.origin.url")
            out.append(os.environ["gsc_repo"] == c_gsc_url)
            print("\nGSC Repo: ", c_gsc_url)
        if os.environ["gsc_commit"]:
            c_gsc_commit = run_subprocess("git branch --show-current")
            out.append(os.environ["gsc_commit"] == c_gsc_commit)
            print("\nGSC Commit: ", c_gsc_commit)
        print("\n\n############################################################################")
        result = all(out)
    else:
        print("No environment variable specified")
        result = True
    return result
