{
  description = "Python env needed to run TimesheetLogic";
  # Provides abstraction to boiler-code when specifying multi-platform outputs.
  inputs.nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
  inputs.flake-parts.url = "github:hercules-ci/flake-parts";
  outputs = inputs@{ self, nixpkgs, flake-parts }: flake-parts.lib.mkFlake { inherit inputs; } {
    systems = [ "x86_64-linux" ];
    perSystem = { config, self', inputs', pkgs, system, ... }: {
      _module.args = {
        pkgs = import nixpkgs {
          inherit system;
          overlays = [
            (final: prev: {
              python3 = prev.python3.override {
                packageOverrides = f: p: {
                  rmscene = pkgs.python3Packages.callPackage ./rmscene.nix {  };
                  rmrl = p.rmrl.overridePythonAttrs (o: {
                    src = self;
                    propagatedBuildInputs = with f; o.propagatedBuildInputs ++ [
                      setuptools
                      rmscene
                    ];
                  });
                };
              };
            })
          ];
        };
      };
      devShells.default = pkgs.mkShell {
        pname = "devshell-rmrl";
        packages = [
          (pkgs.python3.withPackages
            (ps: (with ps.rmrl;
              propagatedBuildInputs ++ nativeBuildInputs)))
        ];
      };
      packages.default = pkgs.python3.withPackages (ps: [ ps.rmscene ps.rmrl]);
    };
  };
}
