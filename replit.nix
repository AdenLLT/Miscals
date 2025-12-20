{ pkgs }: {
  deps = [
    pkgs.glibcLocales
    pkgs.glibc
    pkgs.sqlite.bin
    pkgs.mailutils
  
  ];
  env = {
  };
}