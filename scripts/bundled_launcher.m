// Finder entry point. Resolve every runtime path relative to this application.
#import <Cocoa/Cocoa.h>
#include <unistd.h>

int main(int argc, char **argv) {
    @autoreleasepool {
        NSString *resources = [[NSBundle mainBundle] resourcePath];
        NSString *runtime = [resources stringByAppendingPathComponent:@"runtime"];
        NSString *python = [runtime stringByAppendingPathComponent:@"bin/python3.13"];
        NSString *entry = [resources stringByAppendingPathComponent:@"bundled_entry.py"];
        setenv("PYTHONHOME", [runtime fileSystemRepresentation], 1);
        setenv("PYTHONNOUSERSITE", "1", 1);
        setenv("PYTHONDONTWRITEBYTECODE", "1", 1);
        setenv("PYTHONUNBUFFERED", "1", 1);
        setenv("OKWW_RUNTIME_ROOT", [runtime fileSystemRepresentation], 1);
        setenv("OK_MACOS_HELPER", [[resources stringByAppendingPathComponent:@"ok-macos-helper"] fileSystemRepresentation], 1);
        unsetenv("PYTHONPATH");
        unsetenv("__PYVENV_LAUNCHER__");
        char **arguments = calloc((size_t)argc + 3, sizeof(char *));
        arguments[0] = (char *)[python fileSystemRepresentation];
        arguments[1] = (char *)[entry fileSystemRepresentation];
        for (int i = 1; i < argc; i++) arguments[i + 1] = argv[i];
        execv(arguments[0], arguments);
        NSAlert *alert = [NSAlert new];
        [alert setMessageText:@"OK-WW 启动失败"];
        [alert setInformativeText:@"内置运行环境无法启动。请重新下载完整 App，并查看发布页的安装说明。"];
        [alert runModal];
        return 1;
    }
}
