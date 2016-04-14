#!/usr/bin/env python

from setuptools import setup
import os

rqfiles = [('/usr/share/timmy/' + root, [os.path.join(root, f) for f in files])
               for root, dirs, files in os.walk('rq')]
rqfiles.append(('/usr/share/timmy/configs', ['config.yaml', 'example-config.yaml']))

setup(name='timmy',
      version='0.1',
      author = "Aleksandr Dobdin",
      author_email = 'dobdin@gmail.com',
      license = 'Apache2',
      url = 'https://github.com/adobdin/timmy',
      #  long_description=read('README'),
      packages = ["timmy"],
      data_files = rqfiles,
      include_package_data = True,
      entry_points = {
          'console_scripts': ['timmy = timmy.cli:main']
      }
      )