import inspect
import subprocess
import sys
import yaml
import os


def read_config_yaml(config_file_path, test_name):
    yaml_file = open(config_file_path, "r")
    parsed_yaml_file = yaml.safe_load(yaml_file)
    test_config = parsed_yaml_file["default_input_args"]

    if parsed_yaml_file.get(test_name).get("input_args"):
        test_items = parsed_yaml_file[test_name]["input_args"]
        test_config.update(test_items)
    return test_config


def read_value_config_yaml(config_file_path, test_name, key):
    yaml_file = open(config_file_path, "r")
    parsed_yaml_file = yaml.safe_load(yaml_file)

    if parsed_yaml_file.get(test_name).get(key):
        return parsed_yaml_file.get(test_name).get(key)


def sort_dict(test_config_dict):
    # make sure strings in the order list matches with yaml keys
    # curated app expects inputs in the following order
    input_ord_list = ['signing_key_path', 'attestation', 'ca_cert_path', 'runtime_variables',
                      'runtime_variable_list', 'encrypted_files', 'encrypted_files_path']
    # sort dictionary based on input order list
    return {key: test_config_dict[key] for key in input_ord_list if key in test_config_dict.keys()}


def get_inputs_from_dict(test_config_dict):
    input_str = ''
    for key, value in test_config_dict.items():
        if value:
            input_str += str(value).strip() + "\n"
        else:
            input_str += "\n"
    return input_str


def create_input_file(input_str):
    with open(os.getenv('CURATED_APPS_PATH', "") + "input.txt", mode="w") as f:
        f.write(input_str)
        f.close()


def run_curated_app(base_os):
    os.chdir(os.getenv('CURATED_APPS_PATH', ""))
    process = subprocess.Popen(['python3 curation_app.py ' + base_os + ' < input.txt'], stdout=sys.stdout,
                               stderr=sys.stderr, shell=True)
    process.communicate()
    return process.returncode


def run_test(test_instance, test_yaml_file):
    test_name = inspect.stack()[1].function
    print(f"\n********** Executing {test_name} **********\n")
    test_config_dict = read_config_yaml(test_yaml_file, test_name)
    print(test_config_dict)
    docker_base_os = read_value_config_yaml(test_yaml_file, test_name, 'docker_image')
    print(docker_base_os)
    sorted_dict = sort_dict(test_config_dict)
    print(sorted_dict)
    input_str = get_inputs_from_dict(sorted_dict)
    print(input_str)
    create_input_file(input_str)
    return run_curated_app(docker_base_os)