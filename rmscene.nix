{ lib
, buildPythonPackage
, fetchFromGitHub
, poetry-core
, pythonRelaxDepsHook
, packaging
}:

buildPythonPackage rec {
  pname = "rmscene";
  version = "v0.4.0";
  src = fetchFromGitHub ({
    owner = "ricklupton";
    repo = "rmscene";
    rev = "v0.4.0";
    fetchSubmodules = false;
    sha256 = "sha256-rY3xrzwvMwUn0Vn73I/eCTw+GTjCldBpH+ENY+lhyjk=";
  });
  format = "pyproject";

  nativeBuildInputs = [
    poetry-core
    pythonRelaxDepsHook
  ];

  propagatedBuildInputs = [
    packaging
  ];

  pythonRelaxDeps = [
    "packaging"
  ];

  pythonImportsCheck = [ "rmscene" ];

  meta = {
    description = "Read v6 .rm files from the reMarkable tablet";
    homepage = "https://github.com/ricklupton/rmscene";
    license = lib.licenses.mit;
  };
}
