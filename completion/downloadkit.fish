function _downloadkit_completion;
    set -l response (env _DOWNLOADKIT_COMPLETE_FISH=fish_complete COMP_WORDS=(commandline -cp) COMP_CWORD=(commandline -t) downloadkit);

    for completion in $response;
        set -l metadata (string split "," $completion);

        if test $metadata[1] = "dir";
            __fish_complete_directories $metadata[2];
        else if test $metadata[1] = "file";
            __fish_complete_path $metadata[2];
        else if test $metadata[1] = "plain";
            echo $metadata[2];
        end;
    end;
end;

complete --no-files --command downloadkit --arguments "(_downloadkit_completion)";
