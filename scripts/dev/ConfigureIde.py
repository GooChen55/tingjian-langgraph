"""Save local JetBrains Run/Debug configurations; never start application services."""
from pathlib import Path
import shutil
import time
import uuid
import xml.etree.ElementTree as ET

from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[2]
JAVA = ROOT / 'backend/java/tingshu-parent'
BACKUP = ROOT / '.runtime/ide/backups' / str(time.time_ns())
ENV = dict(dotenv_values(ROOT / '.runtime/ide/application.env', interpolate=False))
JDK = 'D:/develop/JAVA/jdk/ms-17.0.18'
PYTHON_SDK = 'Python 3.13 (AI_tingshu_langgraph)'


def save(path, node):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        target = BACKUP / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    ET.indent(node, space='  ')
    ET.ElementTree(node).write(path, encoding='UTF-8', xml_declaration=True)


def option(node, name, value):
    ET.SubElement(node, 'option', name=name, value=str(value))


def configuration(name, kind, factory):
    component = ET.Element('component', name='ProjectRunConfigurationManager')
    config = ET.SubElement(component, 'configuration', default='false', name=name,
                           type=kind, factoryName=factory)
    return component, config


def environment(config):
    envs = ET.SubElement(config, 'envs')
    for name, value in ENV.items():
        if value is None:
            raise ValueError(f'Missing local environment variable: {name}')
        ET.SubElement(envs, 'env', name=name, value=value)


def compound(directory, name, configurations, filename):
    node, config = configuration(name, 'CompoundRunConfigurationType', 'Compound Run Configuration')
    for child_name, child_type in configurations:
        ET.SubElement(config, 'toRun', name=child_name, type=child_type)
    ET.SubElement(config, 'method', v='2')
    save(directory / filename, node)


def java_configs(project):
    directory = project / '.idea/runConfigurations'
    names = []
    for module, main, label in [
        ('user', 'com.atguigu.tingshu.ServiceUserApplication', 'User-19201'),
        ('album', 'com.atguigu.tingshu.listeningcontent.LocalContentApplication', 'Content-19202'),
        ('order', 'com.atguigu.tingshu.ServiceOrderApplication', 'Order-19204'),
    ]:
        name = f'Tingjian-Java-{label}'
        node, config = configuration(name, 'Application', 'Application')
        option(config, 'MAIN_CLASS_NAME', main)
        option(config, 'ALTERNATIVE_JRE_PATH', JDK)
        option(config, 'ALTERNATIVE_JRE_PATH_ENABLED', 'true')
        option(config, 'VM_PARAMETERS', (ROOT / '.runtime/ide/java.vmoptions').read_text('utf-8'))
        option(config, 'PROGRAM_PARAMETERS', (ROOT / f'.runtime/ide/java-{module}.args').read_text('utf-8'))
        option(config, 'WORKING_DIRECTORY', JAVA.as_posix())
        ET.SubElement(config, 'module', name=f'service-{module}')
        environment(config)
        method = ET.SubElement(config, 'method', v='2')
        ET.SubElement(method, 'option', name='Make', enabled='true')
        save(directory / f'Tingjian_Java_{module}.xml', node)
        names.append((name, 'Application'))
    compound(directory, 'Tingjian-Java-All', names, 'Tingjian_Java_All.xml')
    misc = project / '.idea/misc.xml'
    tree = ET.parse(misc).getroot() if misc.exists() else ET.Element('project', version='4')
    manager = tree.find("component[@name='ProjectRootManager']")
    if manager is None:
        manager = ET.SubElement(tree, 'component', name='ProjectRootManager', version='2')
    manager.set('project-jdk-name', '17')
    manager.set('project-jdk-type', 'JavaSDK')
    manager.set('languageLevel', 'JDK_17')
    runner = tree.find("component[@name='MavenRunner']/option[@name='jreName']")
    if runner is not None:
        runner.set('value', '17')
    maven = tree.find("component[@name='MavenProjectsManager']")
    if maven is None:
        maven = ET.SubElement(tree, 'component', name='MavenProjectsManager')
    originals = maven.find("option[@name='originalFiles']")
    if originals is None:
        originals = ET.SubElement(maven, 'option', name='originalFiles')
    items = originals.find('list')
    if items is None:
        items = ET.SubElement(originals, 'list')
    pom = '$PROJECT_DIR$/pom.xml' if project == JAVA else '$PROJECT_DIR$/backend/java/tingshu-parent/pom.xml'
    if not any(item.get('value') == pom for item in items):
        ET.SubElement(items, 'option', value=pom)
    save(misc, tree)


def python_configs():
    directory = ROOT / '.idea/runConfigurations'
    names = []
    for label, module, params in [
        ('Knowledge-29184', 'uvicorn', '--app-dir python/knowledge app.listening.service:app --host 127.0.0.1 --port 29184'),
        ('Operations-29185', 'uvicorn', '--app-dir python/operations listening.service:app --host 127.0.0.1 --port 29185'),
        ('Worker', 'listening_jobs.worker', f'--project-root "{ROOT.as_posix()}"'),
        ('Assistant-29183', 'uvicorn', '--app-dir python/assistant atguigu.listening.app:app --host 127.0.0.1 --port 29183'),
    ]:
        name = f'Tingjian-Python-{label}'
        node, config = configuration(name, 'PythonConfigurationType', 'Python')
        for key, value in {
            'SDK_HOME': (ROOT / '.venv/Scripts/python.exe').as_posix(),
            'WORKING_DIRECTORY': ROOT.as_posix(), 'IS_MODULE_SDK': 'false',
            'SCRIPT_NAME': module, 'PARAMETERS': params, 'MODULE_MODE': 'true',
            'ADD_CONTENT_ROOTS': 'false', 'ADD_SOURCE_ROOTS': 'false',
            'SHOW_COMMAND_LINE': 'false', 'EMULATE_TERMINAL': 'false',
            'REDIRECT_INPUT': 'false', 'INTERPRETER_OPTIONS': '',
        }.items():
            option(config, key, value)
        environment(config)
        ET.SubElement(config, 'method', v='2')
        save(directory / f'Tingjian_Python_{label}.xml', node)
        names.append((name, 'PythonConfigurationType'))
    # Keep Java and Python compounds in distinct files in the root project.
    compound(directory, 'Tingjian-Python-All', names, 'Tingjian_Python_All.xml')


def python_sdk():
    # Register only this virtual environment, retaining every existing interpreter.
    sdk_file = Path.home() / 'AppData/Roaming/JetBrains/PyCharm2025.3/options/jdk.table.xml'
    tree = ET.parse(sdk_file).getroot()
    table = tree.find("component[@name='ProjectJdkTable']")
    home = (ROOT / '.venv/Scripts/python.exe').as_posix()
    for sdk in table.findall('jdk'):
        if sdk.find('homePath').get('value', '').replace('\\', '/') == home:
            return sdk.find('name').get('value')
    sdk = ET.SubElement(table, 'jdk', version='2')
    for key, value in [('name', PYTHON_SDK), ('type', 'Python SDK'),
                       ('version', 'Python 3.13.9'), ('homePath', home)]:
        ET.SubElement(sdk, key, value=value)
    roots = ET.SubElement(sdk, 'roots')
    classes = ET.SubElement(ET.SubElement(roots, 'classPath'), 'root', type='composite')
    for path in [Path('D:/develop/anaconda3/DLLs'), Path('D:/develop/anaconda3/Lib'),
                 Path('D:/develop/anaconda3'), ROOT / '.venv', ROOT / '.venv/Lib/site-packages']:
        ET.SubElement(classes, 'root', url='file://' + path.as_posix(), type='simple')
    ET.SubElement(ET.SubElement(roots, 'sourcePath'), 'root', type='composite')
    additional = ET.SubElement(sdk, 'additional', ASSOCIATED_PROJECT_PATH=ROOT.as_posix(), SDK_UUID=str(uuid.uuid4()))
    ET.SubElement(additional, 'setting', name='FLAVOR_ID', value='VirtualEnvSdkFlavor')
    ET.SubElement(additional, 'setting', name='FLAVOR_DATA', value='{}')
    BACKUP.mkdir(parents=True, exist_ok=True)
    shutil.copy2(sdk_file, BACKUP / 'pycharm-jdk.table.xml')
    ET.indent(tree, space='  ')
    ET.ElementTree(tree).write(sdk_file, encoding='UTF-8', xml_declaration=True)
    return PYTHON_SDK


def python_project(sdk_name):
    misc = ROOT / '.idea/misc.xml'
    tree = ET.parse(misc).getroot()
    manager = tree.find("component[@name='ProjectRootManager']")
    manager.set('project-jdk-name', sdk_name)
    manager.set('project-jdk-type', 'Python SDK')
    manager.attrib.pop('languageLevel', None)
    maven = tree.find("component[@name='MavenProjectsManager']")
    if maven is not None:
        tree.remove(maven)
    save(misc, tree)
    module_file = ROOT / '.idea/AI_tingshu_langgraph.iml'
    module = ET.Element('module', type='PYTHON_MODULE', version='4')
    settings = ET.SubElement(module, 'component', name='NewModuleRootManager')
    content = ET.SubElement(settings, 'content', url='file://$MODULE_DIR$/..')
    for package in ['shared', 'assistant', 'knowledge', 'operations', 'workers']:
        ET.SubElement(content, 'sourceFolder', url=f'file://$MODULE_DIR$/../python/{package}', isTestSource='false')
    for folder in ['.venv', '.runtime', '.git', 'frontend/uniapp/node_modules', 'frontend/uniapp/dist']:
        ET.SubElement(content, 'excludeFolder', url=f'file://$MODULE_DIR$/../{folder}')
    ET.SubElement(settings, 'orderEntry', type='inheritedJdk')
    ET.SubElement(settings, 'orderEntry', type='sourceFolder', forTests='false')
    save(module_file, module)
    # Remove only the Java launchers generated in the wrong IDE root by this setup.
    for path in (ROOT / '.idea/runConfigurations').glob('Tingjian_Java_*.xml'):
        target = BACKUP / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        path.unlink()


if __name__ == '__main__':
    if not ENV or not (ROOT / '.venv/Scripts/python.exe').is_file():
        raise SystemExit('Run PrepareIde.ps1 first; project interpreter and local environment are required.')
    if not Path(JDK, 'bin/java.exe').is_file():
        raise SystemExit('Configured local JDK 17 is missing.')
    # Separate project roots prevent IDEA and PyCharm from overwriting each other's SDK.
    java_configs(JAVA)
    python_configs()
    python_project(python_sdk())
    print('Saved local JetBrains configurations: 3 Java, 4 Python, and two compound launchers.')
    print('Credentials stay in ignored .idea folders. No services were started.')
