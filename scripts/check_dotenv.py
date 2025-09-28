import sys
try:
    import dotenv
    print('OK', dotenv.__name__, getattr(dotenv, '__version__', 'no-version'))
except Exception as e:
    print('REMOVED: check_dotenv placeholder')
