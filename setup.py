from setuptools import find_packages, setup

setup(
    name='eodms-py',
    version='0.5.0', 
    author='Kevin Ballantyne (Natural Resources Canada)',
    author_email='kevin.ballantyne@nrcan-rncan.gc.ca',
    packages=find_packages(),
    include_package_data=True, 
    # url='https://py-eodms-rapi.readthedocs.io/en/latest/',
    license='LICENSE',
    description='EODMS API Client is a Python3 package used to access the ' \
                'API services provided by the Earth Observation Data ' \
                'Management System (EODMS) from Natural Resources Canada.',
    long_description=open('README.md').read(),
    long_description_content_type="text/markdown",
    install_requires=[
        "dateparser", 
        "pystac-client",
        "requests",
        "tqdm",
    ],
    # project_urls={
    #     "Source": "https://github.com/eodms-sgdot/py-eodms-rapi", 
    #     "Bug Tracker": "https://github.com/eodms-sgdot/py-eodms-rapi/issues",
    # },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.10',
)