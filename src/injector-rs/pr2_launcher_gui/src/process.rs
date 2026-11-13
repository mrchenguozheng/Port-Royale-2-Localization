use std::path::Path;
use std::ptr;

use windows_sys::Win32::Foundation::{CloseHandle, GetLastError, INVALID_HANDLE_VALUE};
use windows_sys::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, Process32FirstW, Process32NextW, PROCESSENTRY32W, TH32CS_SNAPPROCESS,
};
use windows_sys::Win32::System::Threading::{
    CreateProcessA, GetExitCodeProcess, OpenProcess, QueryFullProcessImageNameW, TerminateProcess,
    WaitForSingleObject, CREATE_NO_WINDOW, PROCESS_INFORMATION, PROCESS_QUERY_LIMITED_INFORMATION,
    PROCESS_TERMINATE, STARTUPINFOA,
};

pub enum LaunchError {
    NoLauncher,
    NoLanguage,
    LaunchFailed,
    ExitCode(u32),
}

pub fn launch(root: &Path, lang: Option<&str>, vanilla: bool) -> Result<(), LaunchError> {
    let launcher = root.join("PR2Launcher.exe");
    if !launcher.is_file() {
        return Err(LaunchError::NoLauncher);
    }
    if !vanilla && lang.is_none() {
        return Err(LaunchError::NoLanguage);
    }

    let cmd = if vanilla {
        format!("\"{}\" --vanilla", launcher.display())
    } else {
        format!("\"{}\" --lang={}", launcher.display(), lang.unwrap())
    };
    let mut cmd_c: Vec<u8> = cmd.as_bytes().to_vec();
    cmd_c.push(0);
    let dir = root.to_string_lossy().into_owned();
    let mut dir_c: Vec<u8> = dir.as_bytes().to_vec();
    dir_c.push(0);
    let mut si: STARTUPINFOA = unsafe { std::mem::zeroed() };
    si.cb = std::mem::size_of::<STARTUPINFOA>() as u32;
    let mut pi: PROCESS_INFORMATION = unsafe { std::mem::zeroed() };
    let ok = unsafe {
        CreateProcessA(
            ptr::null(),
            cmd_c.as_mut_ptr(),
            ptr::null(),
            ptr::null(),
            0,
            CREATE_NO_WINDOW,
            ptr::null(),
            dir_c.as_ptr(),
            &si,
            &mut pi,
        )
    };
    if ok == 0 {
        return Err(LaunchError::LaunchFailed);
    }

    let mut code = 0u32;
    unsafe {
        if WaitForSingleObject(pi.hProcess, 4000) == 0 {
            GetExitCodeProcess(pi.hProcess, &mut code);
        }
        CloseHandle(pi.hThread);
        CloseHandle(pi.hProcess);
    }
    if code != 0 {
        return Err(LaunchError::ExitCode(code));
    }
    Ok(())
}

pub fn local_game_processes(root: &Path) -> Vec<u32> {
    let expected = normalize_path(&root.join("PR2.exe").to_string_lossy());
    let mut pids = Vec::new();
    let snapshot = unsafe { CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0) };
    if snapshot == INVALID_HANDLE_VALUE {
        return pids;
    }

    let mut entry: PROCESSENTRY32W = unsafe { std::mem::zeroed() };
    entry.dwSize = std::mem::size_of::<PROCESSENTRY32W>() as u32;
    if unsafe { Process32FirstW(snapshot, &mut entry) } != 0 {
        loop {
            if exe_name(&entry).eq_ignore_ascii_case("PR2.exe") {
                let handle = unsafe {
                    OpenProcess(
                        PROCESS_QUERY_LIMITED_INFORMATION,
                        0,
                        entry.th32ProcessID,
                    )
                };
                if handle != 0 {
                    let mut buf = [0u16; 512];
                    let mut size = buf.len() as u32;
                    let ok = unsafe {
                        QueryFullProcessImageNameW(handle, 0, buf.as_mut_ptr(), &mut size)
                    };
                    if ok != 0 {
                        let path = String::from_utf16_lossy(&buf[..size as usize]);
                        if normalize_path(&path) == expected {
                            pids.push(entry.th32ProcessID);
                        }
                    }
                    unsafe {
                        CloseHandle(handle);
                    }
                }
            }
            if unsafe { Process32NextW(snapshot, &mut entry) } == 0 {
                break;
            }
        }
    }
    unsafe {
        CloseHandle(snapshot);
    }
    pids
}

pub fn terminate(pid: u32) -> Result<(), u32> {
    let handle = unsafe {
        OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_TERMINATE,
            0,
            pid,
        )
    };
    if handle == 0 {
        return Err(unsafe { GetLastError() });
    }
    let ok = unsafe { TerminateProcess(handle, 1) };
    let error = if ok == 0 {
        Some(unsafe { GetLastError() })
    } else {
        None
    };
    unsafe {
        CloseHandle(handle);
    }
    match error {
        Some(code) => Err(code),
        None => Ok(()),
    }
}

fn exe_name(entry: &PROCESSENTRY32W) -> String {
    let mut end = 0usize;
    while end < entry.szExeFile.len() && entry.szExeFile[end] != 0 {
        end += 1;
    }
    String::from_utf16_lossy(&entry.szExeFile[..end])
}

fn normalize_path(path: &str) -> String {
    path.strip_prefix(r"\\?\")
        .unwrap_or(path)
        .replace('/', "\\")
        .to_lowercase()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalizes_windows_path() {
        assert_eq!(normalize_path(r"\\?\C:\Game/PR2.exe"), r"c:\game\pr2.exe");
    }
}
