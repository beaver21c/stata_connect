"""단일 실행파일 진입점(PyInstaller). 인자 없이 실행 시 동작은 stata_agent.cli._default_argv 참조."""

from stata_agent.cli import main

if __name__ == "__main__":
    main()
