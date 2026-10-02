local json = game:GetService("HttpService")

SM = {}
SM.URL = "http://127.0.0.1:1488/"
SM.Connection = false

if not isfolder("soundmodule") then 
    warn("SoundModule couldnt init properly, please run Soundplayer")
    makefolder("soundmodule")
    writefile("soundmodule/Status.txt", "false")
elseif isfolder("soundmodule") and game:HttpGet("http://127.0.0.1:1488/Status") == "Active" then
    SM.Connection = true
    writefile("soundmodule/Status.txt", "true")
    print("SoundModule inited")
end

function SM:Status()
    if isfile("soundmodule/Status.txt") and readfile("soundmodule/Status.txt") == "true" then
        local req = game:HttpGet(self.URL .. "Status")
        if req == "Active" then
            self.Connection = true
            return true
        else
            writefile("soundmodule/Status.txt", "false")
            self.Connection = false
            return false
        end
    else
        self.Connection = false
        return false
    end
end

function SM:IsAudio(audioname: string)
    return isfile("soundmodule/" .. audioname .. ".wav")
end

function SM:GetAudio(link: string, audioname: string)
    if self.Connection then
        if not SM:IsAudio(audioname) then
            local req = game:HttpPost(self.URL .. "Download", json:JSONEncode({
                Link = link,
                AudioName = audioname
            }))
            if req == "Success" then
                return true
            elseif req:find('"error"') then
                error(json:JSONDecode(req).error)
                return false
            end
        else
            return true
        end
    else
        return false
    end
end

function SM:DelAudio(audioname: string)
    if SM:IsAudio(audioname) then
        local req = game:HttpPost(self.URL .. "Del", json:JSONEncode({
            AudioName = audioname
        }))
        if req == "Success" then
            return true
        elseif req:find('"error"') then
            error(json:JSONDecode(req).error)
            return false
        end
    else
        return false
    end
end

function SM:PlayAudio(audioname: string)
    if self.Connection and SM:IsAudio(audioname) then
        local req = game:HttpPost(self.URL .. "Play", json:JSONEncode({
            Audioname = audioname
        }))
        if req == "Success" then
            return true
        elseif req:find('"error"') then
            error(json:JSONDecode(req).error)
            return false
        end
    else
        return false
    end
end

task.spawn(function()
    while SM do
        SM:Status()
        task.wait(3)
    end
end)

return SM