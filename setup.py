from setuptools import setup

setup(
    name='lifecycle',
    version='0.1',
    py_modules=['lifecycle'],
    install_requires=[
        'click',
        'phabricator',
    ],
    entry_points='''
        [console_scripts]
        lifecycle=lifecycle:cli
    ''',
)
